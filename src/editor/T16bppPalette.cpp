// T16bppPalette.cpp - the editor's 16-bit palette (h3maped 0x406562..
// 0x4065a0, between ArtifactsDlg.cpp and BlackBox.cpp; Loki h3maped
// object 6, whose file name follows the class). The Windows release keeps
// only the out-of-line 5:5:5 conversion the map windows call.
#include "va.h"
#include "editor/T16bppBitmap.h"
#include "editor/T16bppPalette.h"

VA(0x0040657e, 0x22)
unsigned short T16bppPalette::rgbToEntry(const TRGB& rgb)
{
    typedef T16bppBitmapBase<unsigned long> Format;
    return ((rgb.red >> (8 - Format::redBits())) << Format::redShift())
         | ((rgb.green >> (8 - Format::greenBits())) << Format::greenShift())
         | ((rgb.blue >> (8 - Format::blueBits())) << Format::blueShift());
}
