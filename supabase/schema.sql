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

-- Buy-in & cashout tracking (added for true-profit stats)
alter table public.sessions add column if not exists cashout numeric;

create table if not exists public.buyins (
  id bigserial primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  amount numeric not null,
  created_at timestamptz not null default now()
);
create index if not exists buyins_session_idx on public.buyins (session_id);
create index if not exists buyins_user_idx on public.buyins (user_id);
alter table public.buyins enable row level security;

alter table public.sessions add column if not exists label text;

create table if not exists public.recap_messages (
  id bigserial primary key,
  session_id bigint not null references public.sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null,
  content text not null,
  created_at timestamptz not null default now()
);
create index if not exists recap_session_idx on public.recap_messages (session_id);
alter table public.recap_messages enable row level security;

create table if not exists public.discord_links (
  id bigserial primary key,
  user_id uuid not null unique references auth.users(id) on delete cascade,
  discord_id text not null,
  discord_username text not null,
  linked_at timestamptz not null default now()
);
alter table public.discord_links enable row level security;

create table if not exists public.bankrolls (
  user_id uuid primary key references auth.users(id) on delete cascade,
  amount numeric(12,2) not null default 0,
  goal numeric(12,2),
  updated_at timestamptz not null default now()
);
alter table public.bankrolls enable row level security;

-- ---------------------------------------------------------------------------
-- Chat usage counters (cost guard). Run in the Supabase SQL editor.
-- 'sessions', 'messages' etc. are ruled by no-policy RLS; these rows are only
-- ever written through the server (service key), never from the browser.
-- ---------------------------------------------------------------------------
create table if not exists public.chat_usage (
  day text not null,
  user_id uuid not null,
  chats bigint not null default 1,
  primary key (day, user_id)
);
alter table public.chat_usage enable row level security;

-- Atomically +1 the counter for (day,user) and the global sentinel, then
-- return both totals so the server can enforce per-user and total caps.
create or replace function public.bump_chat_usage(p_day text, p_user uuid, p_global uuid)
returns table (u_count bigint, g_count bigint)
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.chat_usage (day, user_id, chats) values (p_day, p_user, 1)
    on conflict (day, user_id) do update set chats = public.chat_usage.chats + 1;
  insert into public.chat_usage (day, user_id, chats) values (p_day, p_global, 1)
    on conflict (day, user_id) do update set chats = public.chat_usage.chats + 1;
  return query
    select
      (select chats from public.chat_usage where day = p_day and user_id = p_user),
      (select chats from public.chat_usage where day = p_day and user_id = p_global);
end;
$$;

-- Only the server (service_role) may call it; anons can't inflate the counters.
revoke execute on function public.bump_chat_usage(text, uuid, uuid) from anon, authenticated, public;
grant execute on function public.bump_chat_usage(text, uuid, uuid) to service_role;

-- Each session records the unit its numbers came in. Money math (bankroll,
-- leaderboard, ROI) uses dollar sessions only; bb/chips sessions are tracked
-- for hands/history but never mixed into $ figures. Existing rows = dollars.
alter table public.sessions add column if not exists units text not null default 'dollars';