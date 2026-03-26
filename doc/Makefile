# Build ping-bulk documentation from reStructuredText source.
#
# Requirements: docutils
#   apt install python3-docutils
#   -- or --
#   pip install docutils
#
# Targets:
#   all    — man page + HTML (default)
#   man    — ping-bulk.1
#   html   — ping-bulk.html
#   clean  — remove generated files

RST2MAN  ?= rst2man
RST2HTML ?= rst2html

SRC  = ping-bulk.rst
MAN  = ping-bulk.1
HTML = ping-bulk.html

.PHONY: all man html clean

all: man html

man: $(MAN)

html: $(HTML)

$(MAN): $(SRC)
	$(RST2MAN) $< $@

$(HTML): $(SRC)
	$(RST2HTML) $< $@

clean:
	rm -f $(MAN) $(HTML)

