-- Requeue every video represented in the pasted public.links export.
-- This resets processing state only; the local/GitHub worker then refreshes
-- website descriptions and notes through replace_video_links/replace_video_notes.
-- Keep the local OmniRoute worker running after this query if OmniRoute should
-- process these videos. Existing links and notes remain until each video saves.

begin;

create temporary table requested_retry_videos (
  video_id text primary key
) on commit drop;

insert into requested_retry_videos (video_id) values
  ('-CrwkcKs_40'),
  ('-eRtutPsCPA'),
  ('0AQxZloZYUk'),
  ('0VVvGjybvRo'),
  ('0jHctusPrj0'),
  ('14P-OzCytaw'),
  ('1JpGnZH7PZg'),
  ('1PRAGGatMIs'),
  ('1iXsUqE0d2Y'),
  ('21s0b5Tcmn4'),
  ('2D2XD120YQE'),
  ('2LMHmrF5EC8'),
  ('2T-WCWa5ngw'),
  ('2ax2jMzsIzM'),
  ('2goGyaOz52g'),
  ('2qTIoRR854U'),
  ('31eFCIkNqRI'),
  ('3G7eVgz2Lt4'),
  ('3RkIygI6jP8'),
  ('3gLwyqJgbes'),
  ('3nS2JaAsMEI'),
  ('3scC9dza0Xc'),
  ('4z9yEi8RTRU'),
  ('5udANOsydAo'),
  ('66mZ5fjYjCw'),
  ('6A8DHGig_YY'),
  ('79-SKVWfCu8'),
  ('85jCA1Xhnm0'),
  ('8vyLpQy8rWU'),
  ('AqMKhqGv8fk'),
  ('_Q6Fc_i6qjE'),
  ('c1uIhMQsZMk');

-- Preview all requested IDs. Missing/non-Short rows will not be requeued.
select r.video_id,
       v.title,
       v.is_short,
       v.status,
       v.notes_status,
       case
         when v.video_id is null then 'video row not found'
         when v.is_short is not true then 'not a Short; skipped'
         else 'will be requeued'
       end as action
  from requested_retry_videos r
  left join public.videos v on v.video_id = r.video_id
 order by r.video_id;

update public.videos v
   set status = 'pending',
       error_message = null,
       processed_at = null,
       notes_status = 'pending',
       notes_error_message = null,
       notes_processed_at = null
  from requested_retry_videos r
 where v.video_id = r.video_id
   and v.is_short is true
returning v.video_id, v.title, v.status, v.notes_status;

commit;
