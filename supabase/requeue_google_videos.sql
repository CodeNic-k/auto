-- Preview videos with saved Google links before reprocessing them.
select distinct v.video_id, v.title, v.status, v.notes_status
  from public.videos v
  join public.links l on l.video_id = v.video_id
 where v.is_short is true
   and (l.domain ilike 'google.%' or l.domain ilike 'www.google.%')
 order by v.title;

-- Requeue matching Shorts for a full fresh analysis.
-- The worker replaces the links and notes for each matched video as a set;
-- this does not reprocess just the Google row in isolation.
update public.videos v
   set status = 'pending',
       error_message = null,
       processed_at = null,
       notes_status = 'pending',
       notes_error_message = null,
       notes_processed_at = null
 where v.is_short is true
   and exists (
     select 1
       from public.links l
      where l.video_id = v.video_id
        and (l.domain ilike 'google.%' or l.domain ilike 'www.google.%')
   )
returning v.video_id, v.title;
