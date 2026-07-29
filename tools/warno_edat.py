"""Read-only reader for Eugen's `edat` archives and `TGV` textures.

Build-time only -- the analyzer itself ships the extracted PNGs, so nothing here
ends up in the .exe. Layout follows ev1313/wgrd-cons-parsers, with two things
WARNO does differently from Wargame: the file dictionary header is 9 bytes
rather than 10, and mipmaps are Zstandard frames behind a small `ZSTD` header.

    archive  = 'edat' header -> file dictionary (radix tree of path fragments)
    file     = (offset into the data section, size, md5)
    texture  = TGV header -> per-mipmap offsets/sizes -> ZSTD-packed pixels
"""
import hashlib
import struct

TGV_ZSTD_MAGIC = b'ZSTD'


class EDat:
    """Random access to one .dat archive."""

    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        head = self.f.read(1037)
        if head[:4] != b'edat':
            raise ValueError('%s is not an edat archive' % path)
        (self.offset_files, self.size_files,
         self.offset_data, self.size_data) = struct.unpack_from('<IIII', head, 25)
        (self.sector,) = struct.unpack_from('<I', head, 45)
        self.entries = self._dictionary()

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------------------------------------------------- file table

    def _dictionary(self):
        if not self.size_files:
            return {}
        self.f.seek(self.offset_files)
        block = self.f.read(self.size_files)
        if struct.unpack_from('<I', block, 0)[0] == 1:      # empty archive
            return {}
        for header_len in (9, 10):                          # WARNO / Wargame
            try:
                return self._walk(block, header_len)
            except (AssertionError, struct.error, ValueError, IndexError):
                continue
        raise ValueError('unrecognised file dictionary in %s' % self.path)

    @staticmethod
    def _walk(block, header_len):
        entries = {}

        def name_at(pos):
            end = block.index(b'\x00', pos)
            return block[pos:end].decode('utf-8', 'replace'), end + 1

        def walk(pos, parts, stop):
            while pos != stop:
                assert pos < stop
                start = pos
                path_size, entry_size = struct.unpack_from('<II', block, pos)
                pos += 8
                if path_size:                                # directory node
                    name, pos = name_at(pos)
                    assert pos == start + path_size
                    walk(pos, parts + [name],
                         (start + entry_size) if entry_size else stop)
                else:                                        # file node
                    offset, _, size, _ = struct.unpack_from('<IIII', block, pos)
                    checksum = block[pos + 16:pos + 32]
                    name, pos = name_at(pos + 32)
                    entries[''.join(parts + [name])] = (offset, size, checksum)
                pos = (start + entry_size) if entry_size else stop

        walk(header_len, [], len(block))
        return entries

    # ---------------------------------------------------------------- data

    def read(self, path, verify=True):
        offset, size, checksum = self.entries[path]
        self.f.seek(self.offset_data + offset)
        data = self.f.read(size)
        if verify and hashlib.md5(data).digest() != checksum:
            raise ValueError('checksum mismatch for %s' % path)
        return data

    def find(self, *needles):
        """Entry paths containing every needle, separator-insensitive.

        Older archives use backslashes in stored paths, newer ones use slashes.
        """
        out = []
        for key in self.entries:
            flat = key.replace('\\', '/')
            if all(n.replace('\\', '/') in flat for n in needles):
                out.append(key)
        return out


# -------------------------------------------------------------------- TGV

def _align(n, modulus):
    return (n + modulus - 1) // modulus * modulus


class Texture:
    """A decoded TGV: `width`/`height`, `pixel_format`, and RGBA mip levels."""

    def __init__(self, data):
        (self.version, self.compressed, self.width, self.height,
         image_w, image_h) = struct.unpack_from('<IIIIII', data, 0)
        (self.mip_count,) = struct.unpack_from('<H', data, 24)
        (name_len,) = struct.unpack_from('<H', data, 26)
        self.pixel_format = data[28:28 + name_len].decode('utf-8', 'replace')

        pos = _align(28 + name_len, 8) + 16          # skip the md5 checksum
        offsets = struct.unpack_from('<%dI' % self.mip_count, data, pos)
        pos += 4 * self.mip_count
        sizes = struct.unpack_from('<%dI' % self.mip_count, data, pos)
        self._mips = [data[o:o + s] for o, s in zip(offsets, sizes)]

    def mip_size(self, index):
        """Mipmaps are stored smallest first, so index counts up from the tail."""
        shift = self.mip_count - 1 - index
        return max(1, self.width >> shift), max(1, self.height >> shift)

    def rgba(self, index):
        """RGBA8 bytes for one mip level."""
        if self.pixel_format != 'A8B8G8R8_LIN':
            raise ValueError('unsupported pixel format %r' % self.pixel_format)
        blob = self._mips[index]
        if blob[:4] == TGV_ZSTD_MAGIC:
            import zstandard
            (raw_size,) = struct.unpack_from('<I', blob, 4)
            out = zstandard.ZstdDecompressor().decompress(blob[8:], max_output_size=raw_size)
        else:
            out = blob
        width, height = self.mip_size(index)
        expected = width * height * 4
        if len(out) != expected:
            raise ValueError('mip %d: got %d bytes, expected %d (%dx%d)'
                             % (index, len(out), expected, width, height))
        return out

    def best_mip(self, target):
        """Smallest mip level that is still at least `target` px on its long side."""
        best = self.mip_count - 1
        for i in range(self.mip_count):
            w, h = self.mip_size(i)
            if max(w, h) >= target:
                best = i
                break
        return best


# -------------------------------------------------------------------- PNG

def write_png(rgba, width, height):
    """Minimal RGBA8 PNG, no dependencies."""
    import zlib

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)                              # filter: none
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack('>I', len(payload)) + body + struct.pack('>I', zlib.crc32(body))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + chunk(b'IEND', b''))
