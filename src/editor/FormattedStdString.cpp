// FormattedStdString.cpp - TFormattedStdString's formatter (h3maped
// 0x41e57b..0x41e5c5, between FlaggablePropsDlg.cpp and GameMap.cpp). The
// object includes no editor header but its own: none of the terrain masks'
// initializers open it, as they open every object that includes stdafx.h.
#include <stdarg.h>
#include <stdio.h>
#include <string>

#include "va.h"
#include "editor/FormattedStdString.h"

// Prints into a 4 KB static buffer (h3maped 0x59d250) and assigns the text.
VA(0x0041e597, 0x2e)
void TFormattedStdString::_formatV(const char* format, va_list args)
{
    DATA(0x0059d250) static char buffer[4096];
    vsprintf(buffer, format, args);
    assign(buffer);
}
