-- 1. A removed roommate keeps their history (votes, top-ups, statements); removed_at hides them from everything current.
alter table member add column if not exists removed_at timestamptz;

-- 2. A person can belong to several flats. Each membership keeps its own link; memberships are joined into one
--    person only when that person proves they hold both links (POST /api/me/link).
create table if not exists person (
  id uuid primary key,
  name text not null,
  phone text,
  created_at timestamptz default now()
);
alter table member add column if not exists person_id uuid references person;

-- Backfill: every existing member becomes their own person (same id).
insert into person (id, name, phone, created_at)
  select m.id, m.name, m.phone, m.created_at from member m where m.person_id is null
  on conflict (id) do nothing;
update member set person_id = id where person_id is null;
alter table member alter column person_id set not null;
create index if not exists member_person_idx on member (person_id);
