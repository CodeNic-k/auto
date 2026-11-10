-- Preview Shorts with selected site links, plus the 15 videos from the pasted
-- local-worker log (including malformed-response failures and empty results).
with logged_videos(video_id) as (
  values
    ('_Q6Fc_i6qjE'),
    ('_jv7eeUoWfU'),
    ('_w_Xo3TBTLU'),
    ('-jecFdNlGsI'),
    ('00z65eRob0M'),
    ('-L0tYqW_qBE'),
    ('0So7AUrNdic'),
    ('-RuF4Xh7D_Y'),
    ('1dk09TRqcRI'),
    ('0_x4ehaRr28'),
    ('0ChxN6YQJc8'),
    ('-AQ_Qt4SJYc'),
    ('0ezJxIveYh4'),
    ('0HXqrpL_Y2k'),
    ('-y5A8zOZOaI')
)
select v.video_id,
       v.title,
       v.status,
       v.notes_status,
       array_agg(distinct lower(l.domain) order by lower(l.domain))
         filter (where l.domain is not null
           and (
             lower(l.domain) = 'youtube.com' or lower(l.domain) like '%.youtube.com'
             or lower(l.domain) = 'chatgpt.com' or lower(l.domain) like '%.chatgpt.com'
             or lower(l.domain) = 'huggingface.co' or lower(l.domain) like '%.huggingface.co'
             or lower(l.domain) = 'google.com' or lower(l.domain) like '%.google.com'
           )) as matched_domains
  from public.videos v
  left join public.links l on l.video_id = v.video_id
 where v.is_short is true
   and (
     v.video_id in (select video_id from logged_videos)
     or exists (
       select 1 from public.links matched
        where matched.video_id = v.video_id
          and (
            lower(matched.domain) = 'youtube.com' or lower(matched.domain) like '%.youtube.com'
            or lower(matched.domain) = 'chatgpt.com' or lower(matched.domain) like '%.chatgpt.com'
            or lower(matched.domain) = 'huggingface.co' or lower(matched.domain) like '%.huggingface.co'
            or lower(matched.domain) = 'google.com' or lower(matched.domain) like '%.google.com'
          )
     )
   )
 group by v.video_id, v.title, v.status, v.notes_status
 order by v.title;

-- Requeue these videos and all Shorts already containing one of the selected
-- domains. Existing links stay visible until processing finishes.
with logged_videos(video_id) as (
  values
    ('_Q6Fc_i6qjE'),
    ('_jv7eeUoWfU'),
    ('_w_Xo3TBTLU'),
    ('-jecFdNlGsI'),
    ('00z65eRob0M'),
    ('-L0tYqW_qBE'),
    ('0So7AUrNdic'),
    ('-RuF4Xh7D_Y'),
    ('1dk09TRqcRI'),
    ('0_x4ehaRr28'),
    ('0ChxN6YQJc8'),
    ('-AQ_Qt4SJYc'),
    ('0ezJxIveYh4'),
    ('0HXqrpL_Y2k'),
    ('-y5A8zOZOaI')
)
update public.videos v
   set status = 'pending',
       error_message = null,
       processed_at = null,
       notes_status = 'pending',
       notes_error_message = null,
       notes_processed_at = null
 where v.is_short is true
   and (
     v.video_id in (select video_id from logged_videos)
     or exists (
       select 1 from public.links l
        where l.video_id = v.video_id
          and (
            lower(l.domain) = 'youtube.com' or lower(l.domain) like '%.youtube.com'
            or lower(l.domain) = 'chatgpt.com' or lower(l.domain) like '%.chatgpt.com'
            or lower(l.domain) = 'huggingface.co' or lower(l.domain) like '%.huggingface.co'
            or lower(l.domain) = 'google.com' or lower(l.domain) like '%.google.com'
          )
     )
   )
returning v.video_id, v.title, v.status, v.notes_status;
