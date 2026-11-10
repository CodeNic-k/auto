-- Refresh content saved through 2026-11-10 12:00 Asia/Kolkata (06:30 UTC).
-- Scope is based on website/note created_at and processing timestamps because
-- public.videos has no created_at/discovered_at column. Current status is not
-- a filter: pending, failed, and done Shorts in scope are all reset to pending.
-- Run while the local worker and GitHub processor are stopped.
-- Existing pre-cutoff rows are removed; the worker adds fresh results.
-- Reprocessing is video-level, so later entries on selected videos can also
-- be refreshed. Manual edits/comments on rows being deleted abort this script.

  begin;

  create temporary table refresh_target_videos on commit drop as
  select distinct v.video_id
    from public.videos v
   where v.is_short is true
     and (
       exists (
         select 1 from public.links l
          where l.video_id = v.video_id
            and l.created_at <= timestamptz '2026-11-10 06:30:00+00'
       )
       or exists (
         select 1 from public.notes n
          where n.video_id = v.video_id
            and n.created_at <= timestamptz '2026-11-10 06:30:00+00'
       )
       or v.processed_at <= timestamptz '2026-11-10 06:30:00+00'
       or v.notes_processed_at <= timestamptz '2026-11-10 06:30:00+00'
     );

-- Preview counts before deletion. Later entries on selected videos are shown
-- because a full-video refresh may update them too.
select
  (select count(*) from refresh_target_videos) as shorts_to_reprocess,
  (select count(*) from public.links l
    where l.video_id in (select video_id from refresh_target_videos)
      and l.created_at <= timestamptz '2026-11-10 06:30:00+00') as pre_noon_links_to_remove,
  (select count(*) from public.notes n
    where n.video_id in (select video_id from refresh_target_videos)
      and n.created_at <= timestamptz '2026-11-10 06:30:00+00') as pre_noon_notes_to_remove,
  (select count(*) from public.links l
    where l.video_id in (select video_id from refresh_target_videos)
      and l.created_at > timestamptz '2026-11-10 06:30:00+00') as later_links_on_those_videos,
  (select count(*) from public.notes n
    where n.video_id in (select video_id from refresh_target_videos)
      and n.created_at > timestamptz '2026-11-10 06:30:00+00') as later_notes_on_those_videos;

select v.video_id, v.title, v.status, v.notes_status,
       v.processed_at, v.notes_processed_at
  from public.videos v
 where v.video_id in (select video_id from refresh_target_videos)
 order by v.status, v.title;

do $$
declare
  active_worker boolean := false;
begin
  if to_regclass('public.video_worker_leases') is not null then
    execute 'select exists (select 1 from public.video_worker_leases where lease_name = ''processor'' and expires_at > now())'
       into active_worker;
    if active_worker then
      raise exception 'Refresh stopped: a worker currently owns the video queue. Stop/wait for workers, then rerun.';
    end if;
  end if;

  if exists (
    select 1 from public.links l
     where l.video_id in (select video_id from refresh_target_videos)
       and l.created_at <= timestamptz '2026-11-10 06:30:00+00'
       and (l.manually_edited or exists (
         select 1 from public.content_comments c
          where c.target_type = 'link' and c.target_id = l.id
       ))
  ) or exists (
    select 1 from public.notes n
     where n.video_id in (select video_id from refresh_target_videos)
       and n.created_at <= timestamptz '2026-11-10 06:30:00+00'
       and (n.manually_edited or exists (
         select 1 from public.content_comments c
          where c.target_type = 'note' and c.target_id = n.id
       ))
  ) then
    raise exception 'Refresh stopped: a pre-noon row has a manual edit or comment. Review it before retrying.';
  end if;
end;
$$;

delete from public.links l
 using refresh_target_videos t
 where l.video_id = t.video_id
   and l.created_at <= timestamptz '2026-11-10 06:30:00+00';

delete from public.notes n
 using refresh_target_videos t
 where n.video_id = t.video_id
   and n.created_at <= timestamptz '2026-11-10 06:30:00+00';

-- No status condition: every selected Short is retried, whether pending,
-- failed, or done. The local worker then refreshes its website links and notes.
update public.videos v
   set status = 'pending',
       error_message = null,
       processed_at = null,
       notes_status = 'pending',
       notes_error_message = null,
       notes_processed_at = null
 where v.video_id in (select video_id from refresh_target_videos)
   and v.is_short is true
returning v.video_id, v.title, v.status, v.notes_status;

commit;
