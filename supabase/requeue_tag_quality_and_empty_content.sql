-- Run after redeploying the updated worker and reapplying website_tags.sql.
-- Reprocess every website source so old/generated tag sets are replaced by the
-- new small, shared functional-tag set. User-added tags are kept by the RPC.
-- Also retry completed Shorts that have neither website links nor saved notes.

with website_videos as (
  select distinct ls.video_id
    from public.link_sources ls
  union
  select distinct l.video_id
    from public.links l
),
empty_completed_videos as (
  select v.video_id
    from public.videos v
   where v.status = 'done'
     and v.notes_status = 'done'
     and v.is_short is true
     and not exists (select 1 from public.links l where l.video_id = v.video_id)
     and not exists (select 1 from public.link_sources ls where ls.video_id = v.video_id)
     and not exists (select 1 from public.notes n where n.video_id = v.video_id)
),
target_videos as (
  select video_id from website_videos
  union
  select video_id from empty_completed_videos
)
update public.videos v
   set status = 'pending',
       error_message = null,
       processed_at = null,
       notes_status = 'pending',
       notes_error_message = null,
       notes_processed_at = null
  from target_videos t
 where v.video_id = t.video_id
   and v.is_short is true
returning v.video_id, v.title, v.status, v.notes_status;
