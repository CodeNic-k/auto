-- Run after global_website_dedup.sql.
-- Across the full links table, merge equivalent URL spellings while retaining
-- genuinely different URLs, including Google queries alongside destination URLs.

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
               '^https://www\.', 'https://'
             ),
             '/+$', ''
           ) as canonical_url,
           (array_agg(id order by manually_edited desc, created_at asc, id asc))[1] as keep_id
      from public.links
     group by regexp_replace(
                regexp_replace(
                  regexp_replace(url, '^http://', 'https://'),
                  '^https://www\.', 'https://'
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
                  '^https://www\.', 'https://'
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
                    '^https://www\.', 'https://'
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
               '^https://www\.', 'https://'
             ),
             '/+$', ''
           ) = duplicate_row.canonical_url;
  end loop;
end;
$$;

  -- Canonicalize even URLs that had no duplicate at migration time. This also
  -- makes future inserts from the updated worker match the global unique key.
update public.links
   set url = regexp_replace(
               regexp_replace(
                 regexp_replace(url, '^http://', 'https://'),
                 '^https://www\.', 'https://'
               ),
               '/+$', ''
             );

create unique index if not exists links_url_global_unique_idx on public.links (url);

notify pgrst, 'reload schema';

-- Remove only a Google search whose meaningful query words all identify
-- another link's host/path for the same source video. Distinct Google searches
-- and unrelated websites stay. Edited/commented links are preserved.
with source_links as (
  select id as link_id, video_id from public.links
  union
  select link_id, video_id from public.link_sources
), google_searches as (
  select g.id as link_id,
         s.video_id as source_video_id,
         lower(replace(replace(coalesce(substring(g.url from '[?&]q=([^&]*)'), ''), '+', ' '), '%20', ' ')) as search_query
    from public.links g
    join source_links s on s.link_id = g.id
   where lower(g.url) ~ '^https?://(www\.)?google\.[^/]+/search\?'
     and not g.manually_edited
     and not exists (
       select 1 from public.content_comments c
        where c.target_type = 'link' and c.target_id = g.id
     )
), search_terms as (
  select g.link_id,
         g.source_video_id,
         array_agg(distinct words.word) filter (
           where length(words.word) >= 3
             and words.word not in (
               'a', 'an', 'and', 'app', 'best', 'com', 'find', 'for', 'free',
               'google', 'how', 'in', 'official', 'of', 'on', 'search', 'site',
               'the', 'to', 'tool', 'use', 'website', 'with'
             )
         ) as terms
    from google_searches g
    cross join lateral regexp_split_to_table(g.search_query, '[^a-z0-9]+') as words(word)
   group by g.link_id, g.source_video_id
), redundant_source_pairs as (
  select distinct st.link_id, st.source_video_id
    from search_terms st
    join source_links ds on ds.video_id = st.source_video_id
    join public.links destination on destination.id = ds.link_id
   where destination.id <> st.link_id
     and lower(destination.url) !~ '^https?://(www\.)?google\.'
     and st.terms is not null
     and (
       cardinality(st.terms) >= 2
       or (cardinality(st.terms) = 1 and length(st.terms[1]) >= 6)
     )
     and not exists (
       select 1
         from unnest(st.terms) as query_word(word)
        where not exists (
          select 1
            from regexp_split_to_table(
                   lower(
                     coalesce(destination.domain, '') || ' ' ||
                     coalesce(substring(destination.url from '^[a-z]+://([^/?#]+)'), '') || ' ' ||
                     coalesce(substring(destination.url from '^[a-z]+://[^/]+(/[^?#]*)'), '')
                   ),
                   '[^a-z0-9]+'
                 ) as destination_word(word)
           where destination_word.word = query_word.word
        )
     )
), removed_sources as (
  delete from public.link_sources ls
   using redundant_source_pairs rp
   where ls.link_id = rp.link_id
     and ls.video_id = rp.source_video_id
  returning ls.link_id, ls.video_id
), deleted_google_links as (
  delete from public.links g
   where exists (select 1 from removed_sources rs where rs.link_id = g.id)
     and not g.manually_edited
     and not exists (
       select 1 from public.content_comments c
        where c.target_type = 'link' and c.target_id = g.id
     )
     and not exists (
       select 1 from public.link_sources ls
        where ls.link_id = g.id
          and not exists (
            select 1 from removed_sources rs
             where rs.link_id = ls.link_id and rs.video_id = ls.video_id
          )
     )
  returning g.id, g.url
)
select (select count(*) from deleted_google_links) as redundant_google_links_removed,
       (select count(*) from removed_sources) as matching_video_associations_removed,
       (select count(*) from public.links) as website_entries,
       (select count(distinct url) from public.links) as unique_urls,
       (select count(*) - count(distinct url) from public.links) as duplicate_urls_remaining;
