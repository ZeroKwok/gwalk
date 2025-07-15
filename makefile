.PHONY: build upload

build: clean
	@echo "Building..."
	python -m build

upload:
	twine upload --repository testpypi dist/*
	twine upload dist/*

clean:
	rm -r dist/*