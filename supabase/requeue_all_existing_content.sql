-- Reprocess every Short that already has a website/search or a note.
-- Run after the updated worker has been deployed and the local worker is ready.
-- This only resets queue status. The worker refreshes rows through the existing
-- replacement functions, which preserve manually edited and commented content.

with content_videos as (
  select distinct video_id from public.links
  union
  select distinct video_id from public.link_sources
  union
  select distinct video_id from public.notes
)
update public.videos v
   set status = 'pending',
       error_message = null,
       processed_at = null,
       notes_status = 'pending',
       notes_error_message = null,
       notes_processed_at = null
  from content_videos c
 where v.video_id = c.video_id
   and v.is_short is true
returning v.video_id, v.title, v.status, v.notes_status;
