-- Preview Shorts that contain at least one link on the selected sites.
select v.video_id,
       v.title,
       v.status,
       v.notes_status,
       array_agg(distinct lower(l.domain) order by lower(l.domain)) as matched_domains
  from public.videos v
  join public.links l on l.video_id = v.video_id
 where v.is_short is true
   and (
     lower(l.domain) = 'youtube.com' or lower(l.domain) like '%.youtube.com'
     or lower(l.domain) = 'chatgpt.com' or lower(l.domain) like '%.chatgpt.com'
     or lower(l.domain) = 'huggingface.co' or lower(l.domain) like '%.huggingface.co'
     or lower(l.domain) = 'google.com' or lower(l.domain) like '%.google.com'
   )
 group by v.video_id, v.title, v.status, v.notes_status
 order by v.title;

-- Requeue each matching video for a full fresh analysis.
-- Its other links and notes will be refreshed too, not only the matched domain.
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
        and (
          lower(l.domain) = 'youtube.com' or lower(l.domain) like '%.youtube.com'
          or lower(l.domain) = 'chatgpt.com' or lower(l.domain) like '%.chatgpt.com'
          or lower(l.domain) = 'huggingface.co' or lower(l.domain) like '%.huggingface.co'
          or lower(l.domain) = 'google.com' or lower(l.domain) like '%.google.com'
        )
   )
returning v.video_id, v.title;
