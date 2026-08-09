-- pgvector fluency example (Supabase). Toy dimension (vector(3)) chosen so the numbers
-- stay hand-graspable -- real embeddings from an actual model are 384/768/1536-dim.
-- Stands in for embedding `agent_reasoning` text, which is the planned Phase 2 RAG use
-- case (December). Not wired into AutoTrader's live code.

create extension if not exists vector;

create table notes (
    id          integer   generated always as identity   primary key,
    content     text,
    embedding   vector(3)
);

insert into notes (content, embedding) values ('BUY signal, strong momentum', '[3.0, 1.0, 0.5]');
insert into notes (content, embedding) values ('BUY signal, RSI oversold bounce', '[2.8, 1.2, 0.4]');
insert into notes (content, embedding) values ('BUY signal, breakout confirmed', '[3.2, 0.9, 0.6]');
insert into notes (content, embedding) values ('SELL signal, overbought reversal', '[-2.0, 3.0, 0.5]');
insert into notes (content, embedding) values ('System error, API timeout', '[0.1, -5.0, 10.0]');

-- Cosine distance (<=>) is the right operator for text-embedding similarity: magnitude
-- of the embedding isn't meaningful, direction is. Range is [0, 2] -- 0 is identical
-- direction, 1 is orthogonal, >1 means the vectors point in substantially opposite
-- directions (negative cosine similarity).
--
-- Result against '[3.0, 1.0, 0.5]' (a near-exact match to row 1):
--   BUY signal, strong momentum      -> distance 0
--   BUY signal, breakout confirmed   -> distance 0.0013
--   BUY signal, RSI oversold bounce  -> distance 0.0037
--   System error, API timeout        -> distance 0.9916
--   SELL signal, overbought reversal -> distance 1.2360
--
-- No index (ivfflat/hnsw) needed at this scale -- those only earn their keep past a
-- few thousand rows.

select content, embedding, embedding <=> '[3.0, 1.0, 0.5]' as cosine_distance
from notes
order by embedding <=> '[3.0, 1.0, 0.5]'
limit 5;
