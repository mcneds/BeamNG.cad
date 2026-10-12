# Third-party notices

The project license applies to original BeamNG.cad software only. Dependencies retain their own copyright notices and licenses. The [host-linking exception](LICENSE-EXCEPTION.txt) does not extend to third-party software.

Original project-authored Test Harness and Vehicle Wizard software integrated under `dependencies/cad-calibration/` is covered by the project's software license. Its location under `dependencies/` does not relicense external libraries or the archived model/calibration datasets stored alongside it.

## Dependency licenses

| Component | Use | License / authoritative notice |
| --- | --- | --- |
| Xarial.xCAD 0.8.0 | SolidWorks add-in framework | MIT; the exact notice from the installed 0.8.0 package is reproduced below. [Upstream](https://github.com/xarial/xcad/blob/master/LICENSE.md). |
| CGAL Alpha Wrap 3 and CGAL Python bindings | External geometry worker | GPL-3.0-or-later under the open-source distribution; CGAL also offers commercial licensing. See [CGAL licensing](https://www.cgal.org/license.html), the [Alpha Wrap package](https://doc.cgal.org/latest/Alpha_wrap_3/index.html), and [binding metadata](https://github.com/CGAL/cgal-swig-bindings/blob/main/setup.py). The host exception grants no exception for these components. |
| Blender | External mesh processing and rendering | GNU GPL; retain the installed version's license and notices if redistributing it. See [Blender licensing](https://www.blender.org/about/license/). |
| NumPy | Numerical workers | BSD-3-Clause, with separate notices for bundled components. See [NumPy license](https://github.com/numpy/numpy/blob/main/LICENSE.txt). |
| SciPy | Numerical workers | BSD-3-Clause, with separate notices for bundled components. See [SciPy license](https://github.com/scipy/scipy/blob/main/LICENSE.txt). |
| Matplotlib | Plots and reports | Matplotlib's PSF-based license and bundled third-party notices. See [license agreement](https://matplotlib.org/stable/project/license.html). |
| PySide6 / Qt for Python | Vehicle Wizard UI | LGPLv3 and applicable GPL or commercial alternatives, depending on the Qt component. See [Qt licensing](https://doc.qt.io/qt-6/licensing.html) and [Qt for Python LGPL notice](https://doc.qt.io/qtforpython-6/overviews/qtdoc-lgpl.html). |
| VTK | Vehicle Wizard viewport | BSD-3-Clause and bundled third-party notices. See [VTK copyright notice](https://github.com/Kitware/VTK/blob/master/Copyright.txt). |
| Astro, Starlight, Astro Markdown Remark, Three.js | Documentation website | MIT, as recorded for the installed versions in `website/package-lock.json`; preserve each package's own license and notices. |
| TypeScript, Playwright | Documentation development and tests | Apache-2.0, as recorded in `website/package-lock.json`. |
| Cheerio, Astro Check | Documentation validation | MIT, as recorded in `website/package-lock.json`. |
| Wrangler | Cloudflare deployment tooling | MIT OR Apache-2.0, as recorded in `website/package-lock.json`. |
| SOLIDWORKS and BeamNG.drive | Proprietary host applications | Their respective vendor terms apply. The project license does not grant any rights to those applications or their assets. |

This list identifies direct components used by the project; it is not a replacement for the full license and notice files included in dependency distributions. A redistribution must retain the notices and satisfy the applicable terms for the actual versions and bundled components it includes. Merely running a dependency in a separate process is not a blanket exemption from its license.

## Team models and non-software materials

The Mochi team retains its separate rights to the CAD model and derived materials. CAD/models, meshes, archived vehicle and calibration datasets, screenshots, renders, other non-software assets, and documentation prose are excluded from the project's GPL grant unless their rights holder supplies a separate license. Existing third-party notices and permissions remain authoritative. Public availability does not supply an additional reuse license.

Generated vehicle geometry is not automatically licensed under GPL merely because this software generated it. Copies of project software embedded in output, such as Lua runtime controllers, retain their GPL license and the applicable host-linking exception. Preserve the software license and exception when distributing those copied components.

## Xarial.xCAD 0.8.0 MIT notice

The following notice is reproduced verbatim from `LICENSE.md` in the installed `Xarial.XCad.SolidWorks` 0.8.0 NuGet package:

```text
MIT License

Copyright (c) 2023 Xarial Pty Limited

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
