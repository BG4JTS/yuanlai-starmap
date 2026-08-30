-- ============================================================
-- 《原来是这样》星图平台 · Supabase 建库 SQL
-- 在 Supabase SQL Editor 中执行（一次性）
-- 注意：Data API 已启用；"自动暴露新表"已关闭，故末尾手动 GRANT
-- ============================================================

-- 向量扩展（语义相似）
create extension if not exists vector;

-- ---------- 系列/合集 ----------
create table if not exists public.series (
  id          bigserial primary key,
  name        text not null unique,
  description text,
  source      text not null default 'llm',      -- llm / user
  created_at  timestamptz not null default now()
);

-- ---------- 节目（元数据；正文走静态/Blob） ----------
create table if not exists public.episodes (
  id            bigserial primary key,
  num           int,                             -- 期号（番外可为 null）
  title         text not null,                   -- LLM 修正后标题
  title_raw     text,                            -- RSS 原始标题
  publish_date  date,
  audio_url     text,
  platforms     jsonb,                           -- {ximalaya, xiaoyuzhou, apple}
  duration_sec  int,
  word_count    int,
  transcript_ref text,                           -- 正文路径（Blob/静态）
  summary       text,                            -- LLM 摘要
  tags          text[],                          -- 分层标签 ['植物/银杏',...]
  concepts      text[],                          -- 核心概念
  referenced    text[],                          -- 提到的往期话题（短语; 结构化关联见 edges 表）
  guests        text[],                          -- 嘉宾/科学顾问
  era           text[],                          -- 涉及的历史时期/地质年代
  promised      text[],                          -- 本期挖的坑（"以后细说"的话题）
  embedding     vector(1024),                    -- 摘要嵌入（pgvector）
  series_id     bigint references public.series(id),
  created_at    timestamptz not null default now(),
  unique (num)
);
create index if not exists episodes_series_idx on public.episodes (series_id);
create index if not exists episodes_tags_idx on public.episodes using gin (tags);
create index if not exists episodes_concepts_idx on public.episodes using gin (concepts);
create index if not exists episodes_embedding_idx on public.episodes
  using hnsw (embedding vector_cosine_ops);

-- ---------- 星图边（预计算） ----------
create table if not exists public.edges (
  ep_a      bigint not null references public.episodes(id) on delete cascade,
  ep_b      bigint not null references public.episodes(id) on delete cascade,
  kind      text not null,                       -- series/ref/tag/semantic/concept
  weight    real,
  evidence  text,
  primary key (ep_a, ep_b, kind)
);
create index if not exists edges_a_idx on public.edges (ep_a);
create index if not exists edges_b_idx on public.edges (ep_b);

-- ---------- 坑（社区共建，状态机） ----------
create table if not exists public.pits (
  id           bigserial primary key,
  episode_id   bigint not null references public.episodes(id) on delete cascade,
  ts_sec       int,                              -- 锚定时间戳（秒）
  content      text not null,                    -- 坑内容
  status       text not null default 'open',     -- open/claimed/filled/verified/sleeping
  source       text not null default 'user',     -- user / llm / host
  echo_count   int not null default 0,           -- "我也想知道"共鸣数
  claimant     text,                             -- 认领人（匿名标识）
  filled_by    bigint references public.episodes(id),  -- 被哪期填
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists pits_status_idx on public.pits (status);
create index if not exists pits_episode_idx on public.pits (episode_id);

-- ---------- 填坑记录 ----------
create table if not exists public.fills (
  id          bigserial primary key,
  pit_id      bigint not null references public.pits(id) on delete cascade,
  content     text,
  episode_id  bigint references public.episodes(id),
  source      text not null default 'user',      -- user / host
  verified    boolean not null default false,    -- 主播背书
  created_at  timestamptz not null default now()
);
create index if not exists fills_pit_idx on public.fills (pit_id);

-- ============================================================
-- 行级安全（RLS）
-- ============================================================
alter table public.series   enable row level security;
alter table public.episodes enable row level security;
alter table public.edges    enable row level security;
alter table public.pits     enable row level security;
alter table public.fills    enable row level security;

-- 匿名可读：节目/系列/边/坑/填坑
create policy "public read series"   on public.series   for select using (true);
create policy "public read episodes" on public.episodes for select using (true);
create policy "public read edges"    on public.edges    for select using (true);
create policy "public read pits"     on public.pits     for select using (true);
create policy "public read fills"    on public.fills    for select using (true);

-- 匿名可写：挖坑/填坑/共鸣（应用层限流；可选增强：source 仅 host 可改 verified）
create policy "anon insert pits" on public.pits for insert with check (true);
create policy "anon insert fills" on public.fills for insert with check (true);

-- ============================================================
-- 手动授权 Data API（因"自动暴露新表"已关闭）
-- ============================================================
grant select on public.series, public.episodes, public.edges, public.pits, public.fills to anon, authenticated;
grant insert on public.pits, public.fills to anon, authenticated;

-- ============================================================
-- 备注
-- - export_db.py 用 service role key 写入（绕过 RLS），故无需额外写权限
-- - "我也想知道"（echo）更新用 update policy：如需匿名 update，自行添加
--   create policy "anon echo pits" on public.pits for update using (true) with check (true);
-- ============================================================
