-- Run after site_collaboration.sql. Replace the address with the exact email
-- already listed in Supabase Authentication > Users.
insert into public.site_editors (user_id)
select id
  from auth.users
 where lower(email) = lower('replace-with-your-demo-email@gmail.com')
on conflict (user_id) do nothing
returning user_id;

-- If no row is returned, check that the email matches an existing Auth user.
