--This sample code is one of the statements that the Python script generates. 
CREATE TABLE wawa_locations
(
  locationid integer NOT NULL,
  objectid text,
  hasmenu boolean,
  areamanager text,
  open24hours boolean,
  address text,
  city text,
  state text,
  zip text,
  longitude double precision,
  latitude double precision,
  regionaldirector text,
  telephone text,
  isactive boolean,
  storename text,
  lastupdated timestamp without time zone,
  storenumber integer,
  storeopen time without time zone,
  storeclose time without time zone,
  hasfuel boolean,
  unleadedprice double precision,
  plusprice double precision,
  premiumprice double precision,
  geom geometry,
  CONSTRAINT wawatest_pkey PRIMARY KEY (locationid)
)