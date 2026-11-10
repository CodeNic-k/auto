-- Run after site_collaboration.sql.
-- Store one website row per exact normalized URL while retaining every video
-- that surfaced it, so each video's notes remain available from that website.

create table if not exists public.link_sources (
  link_id bigint not null references public.links(id) on delete cascade,
  video_id text not null references public.videos(video_id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (link_id, video_id)
);

create index if not exists link_sources_video_id_idx
  on public.link_sources (video_id);

alter table public.link_sources enable row level security;
revoke all on public.link_sources from public, anon, authenticated;
grant select on public.link_sources to anon, authenticated;
drop policy if exists "Public can read link sources" on public.link_sources;
create policy "Public can read link sources"
  on public.link_sources for select to anon, authenticated using (true);

-- Seed source mappings from current rows before consolidating old duplicates.
insert into public.link_sources (link_id, video_id)
select id, video_id from public.links
on conflict do nothing;

-- Keep one canonical row per exact URL. Prefer manually-edited rows, then the
-- oldest row, so existing comments and editorial work have a stable home.
do $$
declare
  duplicate_row record;
  canonical_id bigint;
begin
  for duplicate_row in
    select url, (array_agg(id order by manually_edited desc, created_at asc, id asc))[1] as keep_id
      from public.links
     group by url
    having count(*) > 1
  loop
    canonical_id := duplicate_row.keep_id;

    insert into public.link_sources (link_id, video_id)
    select canonical_id, video_id
      from public.link_sources
     where link_id in (select id from public.links where url = duplicate_row.url)
    on conflict do nothing;

    update public.content_comments c
       set target_id = canonical_id
     where c.target_type = 'link'
       and c.target_id in (select id from public.links where url = duplicate_row.url)
       and c.target_id <> canonical_id;

    delete from public.links
     where url = duplicate_row.url and id <> canonical_id;
  end loop;
end;
$$;

create unique index if not exists links_url_global_unique_idx on public.links (url);

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

  insert into public.links as existing (video_id, url, domain, description, category)
  select p_video_id, row_data.url, row_data.domain, row_data.description, row_data.category
    from jsonb_to_recordset(p_rows) as row_data(
      url text, domain text, description text, category text
    )
  on conflict (url) do update
    set domain = excluded.domain,
        description = case when existing.manually_edited
                           then existing.description else excluded.description end,
        category = case when existing.manually_edited
                        then existing.category else excluded.category end;

  insert into public.link_sources (link_id, video_id)
  select l.id, p_video_id
    from public.links l
    join jsonb_to_recordset(p_rows) as row_data(url text) on row_data.url = l.url
  on conflict do nothing;

  delete from public.link_sources ls
   using public.links l
   where ls.link_id = l.id
     and ls.video_id = p_video_id
     and not exists (
       select 1 from jsonb_to_recordset(p_rows) as row_data(url text)
        where row_data.url = l.url
     )
     and not l.manually_edited
     and not exists (
       select 1 from public.content_comments c
        where c.target_type = 'link' and c.target_id = l.id
     );

  delete from public.links l
   where not l.manually_edited
     and not exists (select 1 from public.link_sources ls where ls.link_id = l.id)
     and not exists (
       select 1 from public.content_comments c
        where c.target_type = 'link' and c.target_id = l.id
     );

  get diagnostics affected_rows = row_count;
  return affected_rows;
end;
$$;

revoke all on function public.replace_video_links(text, jsonb) from public, anon, authenticated;
grant execute on function public.replace_video_links(text, jsonb) to service_role;

notify pgrst, 'reload schema';
