-- Run after global_website_dedup.sql.
-- Merge common URL spelling variants created before worker-side canonicalization.

drop index if exists public.links_url_global_unique_idx;

do $$
declare
  duplicate_row record;
  canonical_id bigint;
begin
  for duplicate_row in
    select regexp_replace(
             regexp_replace(
               regexp_replace(url, '^http://', 'https://'),
               '^https://www\\.', 'https://'
             ),
             '/+$', ''
           ) as canonical_url,
           (array_agg(id order by manually_edited desc, created_at asc, id asc))[1] as keep_id
      from public.links
     group by regexp_replace(
                regexp_replace(
                  regexp_replace(url, '^http://', 'https://'),
                  '^https://www\\.', 'https://'
                ),
                '/+$', ''
              )
    having count(*) > 1
  loop
    canonical_id := duplicate_row.keep_id;

    insert into public.link_sources (link_id, video_id)
    select canonical_id, video_id
      from public.link_sources
     where link_id in (
       select id from public.links
        where regexp_replace(
                regexp_replace(
                  regexp_replace(url, '^http://', 'https://'),
                  '^https://www\\.', 'https://'
                ),
                '/+$', ''
              ) = duplicate_row.canonical_url
     )
    on conflict do nothing;

    update public.content_comments c
       set target_id = canonical_id
     where c.target_type = 'link'
       and c.target_id in (
         select id from public.links
          where regexp_replace(
                  regexp_replace(
                    regexp_replace(url, '^http://', 'https://'),
                    '^https://www\\.', 'https://'
                  ),
                  '/+$', ''
                ) = duplicate_row.canonical_url
       )
       and c.target_id <> canonical_id;

    update public.links
       set url = duplicate_row.canonical_url
     where id = canonical_id;

    delete from public.links
     where id <> canonical_id
       and regexp_replace(
             regexp_replace(
               regexp_replace(url, '^http://', 'https://'),
               '^https://www\\.', 'https://'
             ),
             '/+$', ''
           ) = duplicate_row.canonical_url;
  end loop;
end;
$$;

create unique index if not exists links_url_global_unique_idx on public.links (url);

notify pgrst, 'reload schema';