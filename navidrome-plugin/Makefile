# Nomarr Navidrome Plugin — Build & Package
#
# Standard Go 1.24+ is used by default (supports //go:wasmexport natively).
# Set USE_TINYGO=1 to build with TinyGo instead.

.PHONY: build package clean

SRC_DIR     := src
DIST_DIR    := dist
WASM_OUT    := $(DIST_DIR)/plugin.wasm
NDP_OUT     := $(DIST_DIR)/nomarr.ndp
NDP_FILES   := $(WASM_OUT) manifest.json

ifdef USE_TINYGO
  BUILD_CMD = cd $(SRC_DIR) && tinygo build -target=wasip1 -scheduler=none -buildmode=c-shared -o ../$(WASM_OUT) .
else
  BUILD_CMD = cd $(SRC_DIR) && GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o ../$(WASM_OUT) .
endif

build: | $(DIST_DIR)
	$(BUILD_CMD)

$(DIST_DIR):
	mkdir -p $(DIST_DIR)

package: build
	cp manifest.json $(DIST_DIR)/manifest.json
	cd $(DIST_DIR) && zip -j ../$(NDP_OUT) plugin.wasm manifest.json

clean:
	rm -rf $(DIST_DIR)
