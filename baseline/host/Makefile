# r1a_host -- host side of the R1A harness. TEST-ONLY.
#
#   make            build
#   make check      everything testable without a USB device
#
# No libusb: its set_configuration path is the one the experiment must avoid
# (see the file header). Only kernel uapi headers are needed.
CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -Werror
TARGET   = r1a_host

all: $(TARGET)

$(TARGET): r1a_host.c
	$(CC) $(CFLAGS) -o $@ $<

check: $(TARGET)
	./selftest.sh

clean:
	rm -f $(TARGET) *.o harness.log session.json

.PHONY: all check clean
