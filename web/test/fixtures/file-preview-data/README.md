These tiny fixtures were generated for Focus regression tests; they contain no user data.

- `sample.bmp`, `sample.ico`: 16×16 blue image generated with Pillow.
- `sample.gif`: 16×16 two-frame red/blue animation generated with Pillow.
- `sample.avif`: 16×16 blue image generated with ImageMagick/libheif.
- `sample.pdf`: two pages of Helvetica text and a blue rectangle, generated with pypdf.
  Its JavaScript open action tries `fetch('https://example.test/pdf-script')`; the
  preview must never execute it.
- `encrypted.pdf`: the same PDF with test password `preview-password` (RC4-128).
- `rotated.pdf`, `large-page.pdf`: its first page rotated 90 degrees, or assigned
  a 100000×100000 media box, for text positioning and Canvas memory bounds.
- `jpeg2000.pdf`: a red JPEG 2000 image generated with Pillow/OpenJPEG and embedded
  by pypdf; tests exercise the packaged decoder under the application CSP.

Tests consume the checked-in files. These generators are not build, runtime or CI dependencies.
