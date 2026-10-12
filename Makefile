PY ?= python3
.PHONY: setup simulate dashboard test clean
setup:      ; $(PY) -m pip install -r requirements.txt
simulate:   ; $(PY) -m src.simulate --batches 6 --rows 25000
dashboard:  ; streamlit run dashboard/app.py
test:       ; $(PY) -m pytest -q
clean:      ; rm -rf data/dq.db data/incoming logs
