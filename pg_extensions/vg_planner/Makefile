# vg_planner — PGXS build. See docker/planner-pg/Dockerfile for the image build.
MODULE_big = vg_planner
OBJS = src/vg_planner.o src/advice_parse.o src/advice_state.o src/advice_rules.o \
       src/advice_check.o src/pg18_joinsearch.o

EXTENSION = vg_planner
DATA = vg_planner--0.1.sql vg_planner--0.1--0.2.sql

REGRESS = inert equivalence advice
REGRESS_OPTS = --inputdir=test --outputdir=test

PG_CPPFLAGS = -I$(srcdir)/src
PG_CFLAGS = -Wall -Wmissing-prototypes -Werror

PG_CONFIG ?= pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)
