-- Run after the worker has finished processing the tag-quality requeue.
-- Any rows returned still need at least one approved tag.

select l.id, l.url, l.domain, l.description, l.category
  from public.links l
 where not exists (
   select 1
     from public.link_tags t
    where t.link_id = l.id
      and t.status = 'approved'
 )
 order by l.domain, l.id;
