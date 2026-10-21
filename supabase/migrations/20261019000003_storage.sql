-- Call recordings: private bucket. Contains personal data (voice, phone numbers, health info).
-- Object path convention: {business_id}/{call_id}.{ext}
-- Uploads happen server-side with the service role. Owners read via short-lived signed URLs,
-- which Storage only issues if this SELECT policy allows the object.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('recordings', 'recordings', false, 52428800,
        array['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/ogg', 'audio/webm'])
on conflict (id) do nothing;

create function public.storage_object_business_id(object_name text) returns uuid
language sql immutable set search_path = '' as $$
  select case
    when split_part(object_name, '/', 1) ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    then split_part(object_name, '/', 1)::uuid
  end;
$$;

create policy recordings_select_own_business on storage.objects
  for select to authenticated
  using (
    bucket_id = 'recordings'
    and public.is_business_member(public.storage_object_business_id(name))
  );
