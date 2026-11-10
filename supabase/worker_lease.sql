-- Run once in the Supabase SQL Editor for the project used by the workers.
-- This lease prevents overlapping local worker processes from taking the queue
-- at the same time.

create table if not exists public.video_worker_leases (
  lease_name text primary key check (lease_name = 'processor'),
  owner_id text not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null default now()
);

grant usage on schema public to service_role;
alter table public.video_worker_leases enable row level security;
revoke all on public.video_worker_leases from public, anon, authenticated, service_role;

create or replace function public.try_acquire_video_worker_lease(
  p_owner_id text,
  p_lease_seconds integer default 180
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  affected_rows integer;
begin
  if p_owner_id is null or length(trim(p_owner_id)) = 0 then
    raise exception 'p_owner_id is required';
  end if;
  if p_lease_seconds is null or p_lease_seconds < 10 or p_lease_seconds > 7200 then
    raise exception 'p_lease_seconds must be between 10 and 7200';
  end if;

  insert into public.video_worker_leases (lease_name, owner_id, expires_at, updated_at)
  values ('processor', p_owner_id, now() + make_interval(secs => p_lease_seconds), now())
  on conflict (lease_name) do update
    set owner_id = excluded.owner_id,
        expires_at = excluded.expires_at,
        updated_at = now()
    where public.video_worker_leases.expires_at <= now()
       or public.video_worker_leases.owner_id = excluded.owner_id;

  get diagnostics affected_rows = row_count;
  return affected_rows = 1;
end;
$$;

create or replace function public.renew_video_worker_lease(
  p_owner_id text,
  p_lease_seconds integer default 180
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_lease_seconds is null or p_lease_seconds < 10 or p_lease_seconds > 7200 then
    raise exception 'p_lease_seconds must be between 10 and 7200';
  end if;

  update public.video_worker_leases
     set expires_at = now() + make_interval(secs => p_lease_seconds),
         updated_at = now()
   where lease_name = 'processor'
     and owner_id = p_owner_id
     and expires_at > now();
  return found;
end;
$$;

create or replace function public.release_video_worker_lease(p_owner_id text)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_owner_id is null or length(trim(p_owner_id)) = 0 then
    raise exception 'p_owner_id is required';
  end if;
  delete from public.video_worker_leases
   where lease_name = 'processor' and owner_id = p_owner_id;
  return found;
end;
$$;

revoke all on function public.try_acquire_video_worker_lease(text, integer) from public, anon, authenticated;
revoke all on function public.renew_video_worker_lease(text, integer) from public, anon, authenticated;
revoke all on function public.release_video_worker_lease(text) from public, anon, authenticated;
grant execute on function public.try_acquire_video_worker_lease(text, integer) to service_role;
grant execute on function public.renew_video_worker_lease(text, integer) to service_role;
grant execute on function public.release_video_worker_lease(text) to service_role;

notify pgrst, 'reload schema';
