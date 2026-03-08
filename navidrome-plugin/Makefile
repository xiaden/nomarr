# Nomarr Navidrome Plugin — Build & Package
#
# Standard Go 1.24+ is used by default (supports //go:wasmexport natively).
# Set USE_TINYGO=1 to build with TinyGo instead.

.PHONY: build package clean

WASM_OUT    := plugin.wasm
NDP_OUT     := nomarr.ndp
NDP_FILES   := $(WASM_OUT) manifest.json

ifdef USE_TINYGO
  BUILD_CMD = tinygo build -target=wasip1 -scheduler=none -buildmode=c-shared -o $(WASM_OUT) .
else
  BUILD_CMD = GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o $(WASM_OUT) .
endif

build:
	$(BUILD_CMD)

package: build
	zip -j $(NDP_OUT) $(NDP_FILES)

clean:
	rm -f $(WASM_OUT) $(NDP_OUT)
