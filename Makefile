MAIN ?= paper

LATEX_AUX = \
	$(MAIN).aux \
	$(MAIN).bbl \
	$(MAIN).blg \
	$(MAIN).fdb_latexmk \
	$(MAIN).fls \
	$(MAIN).log \
	$(MAIN).out \
	$(MAIN).synctex.gz

.PHONY: build clean distclean

build:
	latexmk -pdf $(MAIN).tex

clean:
	rm -f $(LATEX_AUX)

distclean: clean
	rm -f $(MAIN).pdf
