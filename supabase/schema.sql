-- Run this in the Supabase SQL editor.
-- Social: profiles + friends. Access goes through the backend (service key),
-- so RLS is enabled with NO policies -> anon/authenticated clients are denied.

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists public.friends (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  friend_id uuid not null references auth.users(id) on delete cascade,
  status text not null default 'pending' check (status in ('pending', 'accepted')),
  created_at timestamptz not null default now(),
  unique (user_id, friend_id)
);

create index if not exists friends_user_id_idx on public.friends (user_id);
create index if not exists friends_friend_id_idx on public.friends (friend_id);

alter table public.profiles enable row level security;
alter table public.friends enable row level security;