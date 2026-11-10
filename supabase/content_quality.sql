-- Run once in Supabase SQL Editor after deploying the updated worker code.
-- Adds the workflow category, atomically replaces old extracted content, and
-- queues existing Shorts for a fresh OmniRoute analysis.

do $$
declare
  constraint_row record;
begin
  for constraint_row in
    select conname
      from pg_constraint
     where conrelid = 'public.links'::regclass
       and contype = 'c'
       and pg_get_constraintdef(oid) ilike '%category%'
  loop
    execute format('alter table public.links drop constraint %I', constraint_row.conname);
  end loop;

  for constraint_row in
    select conname
      from pg_constraint
     where conrelid = 'public.notes'::regclass
       and contype = 'c'
       and pg_get_constraintdef(oid) ilike '%category%'
  loop
    execute format('alter table public.notes drop constraint %I', constraint_row.conname);
  end loop;
end;
$$;

alter table public.links
  add constraint links_category_check
  check (category in (
    'AI tools', 'Productivity', 'Design', 'Dev tools', 'Privacy/Security',
    'Free resources', 'Learning', 'Entertainment', 'How-to & workflows', 'Other'
  ));

alter table public.notes
  add constraint notes_category_check
  check (category in (
    'AI tools', 'Productivity', 'Design', 'Dev tools', 'Privacy/Security',
    'Free resources', 'Learning', 'Entertainment', 'How-to & workflows', 'Other'
  ));

create or replace function public.replace_video_links(p_video_id text, p_rows jsonb)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  affected_rows integer;
begin
  if p_video_id is null or length(trim(p_video_id)) = 0 then
    raise exception 'p_video_id is required';
  end if;
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'p_rows must be a JSON array';
  end if;

  delete from public.links where video_id = p_video_id;

  insert into public.links (video_id, url, domain, description, category)
  select p_video_id, row_data.url, row_data.domain, row_data.description, row_data.category
    from jsonb_to_recordset(p_rows) as row_data(
      url text, domain text, description text, category text
    )
  on conflict (video_id, url) do update
    set domain = excluded.domain,
        description = excluded.description,
        category = excluded.category;

  get diagnostics affected_rows = row_count;
  return affected_rows;
end;
$$;

create or replace function public.replace_video_notes(p_video_id text, p_rows jsonb)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  affected_rows integer;
begin
  if p_video_id is null or length(trim(p_video_id)) = 0 then
    raise exception 'p_video_id is required';
  end if;
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'p_rows must be a JSON array';
  end if;

  delete from public.notes where video_id = p_video_id;

  insert into public.notes (video_id, title, detail, category)
  select p_video_id, row_data.title, row_data.detail, row_data.category
    from jsonb_to_recordset(p_rows) as row_data(
      title text, detail text, category text
    )
  on conflict (video_id, title) do update
    set detail = excluded.detail,
        category = excluded.category;

  get diagnostics affected_rows = row_count;
  return affected_rows;
end;
$$;

grant usage on schema public to service_role;
revoke all on function public.replace_video_links(text, jsonb) from public, anon, authenticated;
revoke all on function public.replace_video_notes(text, jsonb) from public, anon, authenticated;
grant execute on function public.replace_video_links(text, jsonb) to service_role;
grant execute on function public.replace_video_notes(text, jsonb) to service_role;

notify pgrst, 'reload schema';
