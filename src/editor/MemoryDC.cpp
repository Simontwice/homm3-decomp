// MemoryDC.cpp - the editor's memory DC errors and GDI helpers (h3maped
// 0x486f98..0x487715, name inferred). drawTransparentBitmap masks the
// transparent colour out of the bitmap and the bitmap out of the
// background in memory, then copies the combination in one blit.
#include "editor/stdafx.h"

#include "va.h"
#include "editor/DCAttributeSelector.h"
#include "editor/GDIObjectSelector.h"
#include "editor/MemoryDC.h"

VA(0x00486fb4, 0x6a)
COLORREF getTransparentColor(CBitmap* pBitmap)
{
    CDC dc;
    dc.CreateCompatibleDC(NULL);
    TGDIObjectSelector<CBitmap> selector(&dc, pBitmap);
    return ::GetPixel(dc.m_hDC, 0, 0);
}

VA(0x0048701e, 0x12)
TMemoryDC::TError::TError()
{
}

VA(0x00487030, 0x12)
TGDIObjectSelectorError::TGDIObjectSelectorError()
{
}

VA(0x00487042, 0x4df)
void drawTransparentBitmap(CDC* pDC, CBitmap* pBitmap, int x, int y, COLORREF transparentColor)
{
    BITMAP bitmap;
    pBitmap->GetBitmap(&bitmap);
    CSize size(bitmap.bmWidth, bitmap.bmHeight);
    CDC imageDC;
    CDC inverseMaskDC;
    CDC maskDC;
    CDC backgroundDC;
    CDC foregroundDC;
    CBitmap maskBitmap;
    CBitmap inverseMaskBitmap;
    CBitmap backgroundBitmap;
    CBitmap foregroundBitmap;
    try {
        if (!imageDC.CreateCompatibleDC(pDC))
            return;
        TGDIObjectSelector<CBitmap> imageSelector(&imageDC, pBitmap);
        if (!inverseMaskDC.CreateCompatibleDC(pDC)
            || !maskBitmap.CreateBitmap(size.cx, size.cy, 1, 1, NULL))
            return;
        TGDIObjectSelector<CBitmap> inverseMaskSelector(&inverseMaskDC, &maskBitmap);
        if (!maskDC.CreateCompatibleDC(pDC)
            || !inverseMaskBitmap.CreateBitmap(size.cx, size.cy, 1, 1, NULL))
            return;
        TGDIObjectSelector<CBitmap> maskSelector(&maskDC, &inverseMaskBitmap);
        if (!backgroundDC.CreateCompatibleDC(pDC)
            || !backgroundBitmap.CreateCompatibleBitmap(pDC, size.cx, size.cy))
            return;
        TGDIObjectSelector<CBitmap> backgroundSelector(&backgroundDC, &backgroundBitmap);
        if (!foregroundDC.CreateCompatibleDC(pDC)
            || !foregroundBitmap.CreateCompatibleBitmap(pDC, size.cx, size.cy))
            return;
        TGDIObjectSelector<CBitmap> foregroundSelector(&foregroundDC, &foregroundBitmap);
        {
            TBkColorSelector bkColorSelector(&imageDC, transparentColor);
            maskDC.BitBlt(0, 0, size.cx, size.cy, &imageDC, 0, 0, SRCCOPY);
        }
        inverseMaskDC.BitBlt(0, 0, size.cx, size.cy, &maskDC, 0, 0, NOTSRCCOPY);
        backgroundDC.BitBlt(0, 0, size.cx, size.cy, pDC, x, y, SRCCOPY);
        backgroundDC.BitBlt(0, 0, size.cx, size.cy, &maskDC, 0, 0, SRCAND);
        foregroundDC.BitBlt(0, 0, size.cx, size.cy, &imageDC, 0, 0, SRCCOPY);
        foregroundDC.BitBlt(0, 0, size.cx, size.cy, &inverseMaskDC, 0, 0, SRCAND);
        backgroundDC.BitBlt(0, 0, size.cx, size.cy, &foregroundDC, 0, 0, SRCPAINT);
        pDC->BitBlt(x, y, size.cx, size.cy, &backgroundDC, 0, 0, SRCCOPY);
    } catch (...) {
    }
}

VA(0x00487521, 0x22)
void drawTransparentBitmap(CDC* pDC, CBitmap* pBitmap, int x, int y)
{
    drawTransparentBitmap(pDC, pBitmap, x, y, getTransparentColor(pBitmap));
}

VA(0x00487543, 0x72)
bool isPixelColor(CBitmap* pBitmap, int x, int y, COLORREF color)
{
    CDC dc;
    dc.CreateCompatibleDC(NULL);
    TGDIObjectSelector<CBitmap> selector(&dc, pBitmap);
    return ::GetPixel(dc.m_hDC, x, y) == color;
}

VA(0x004875b5, 0x1f)
bool isTransparentPixel(CBitmap* pBitmap, int x, int y)
{
    return isPixelColor(pBitmap, x, y, getTransparentColor(pBitmap));
}

VA(0x004875d4, 0x3f)
unsigned int getFirstMenuItem(CMenu* pMenu)
{
    unsigned int index = 0;
    MENUITEMINFO info;
    info.cbSize = sizeof(info);
    info.fMask = MIIM_TYPE;
    info.dwTypeData = NULL;
    for (;;) {
        info.cch = 0;
        pMenu->GetMenuItemInfo(index, &info, TRUE);
        if (!(info.fType & MFT_SEPARATOR))
            break;
        index++;
    }
    return index;
}

VA(0x00487613, 0xbb)
bool setMenuItemText(CMenu* pMenu, unsigned int& index, CString text)
{
    MENUITEMINFO info;
    info.cbSize = sizeof(info);
    info.fMask = MIIM_TYPE;
    info.dwTypeData = NULL;
    info.cch = 0;
    pMenu->GetMenuItemInfo(index, &info, TRUE);
    info.dwTypeData = text.GetBuffer(0);
    ::SetMenuItemInfo(pMenu->m_hMenu, index, TRUE, &info);
    text.ReleaseBuffer();
    info.dwTypeData = NULL;
    for (;;) {
        index++;
        if (index >= pMenu->GetMenuItemCount())
            return false;
        info.cch = 0;
        pMenu->GetMenuItemInfo(index, &info, TRUE);
        if (!(info.fType & MFT_SEPARATOR))
            return true;
    }
}
