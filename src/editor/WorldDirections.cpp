// WorldDirections.cpp - the compass names and the part of the map a
// location lies in (h3maped 0x4cd567..0x4cd7ae; GOG only).
#include "editor/stdafx.h"

#include <string.h>

#include "autoarrayptr.h"
#include "exceptions.h"
#include "resourcemanager.h"
#include "resourceptr.h"
#include "textresource.h"
#include "va.h"
#include "editor/WorldDirections.h"

namespace {
DATA(0x005a6ae0) const char* aWorldDirectionNamesImp[kNumWorldDirections];
}

DATA(0x00593820) const char** akWorldDirectionNames = aWorldDirectionNamesImp;

VA(0x004cd583, 0x181)
void InitializeWorldDirectionNamesTable()
{
    TResourcePtr<TTextResource> pTextResource(ResourceManager::GetText("ArrayTxt.txt"));
    if (!pTextResource.get())
        throw TRuntimeError();
    int first;
    for (first = 0;; first++) {
        if (first >= pTextResource->GetNumberOfStrings())
            throw TRuntimeError();
        if (strcmp(pTextResource->GetText(first), "cDirections") == 0)
            break;
    }
    first++;
    int last = first + kNumWorldDirections;
    unsigned int namesSize = 0;
    int i;
    for (i = first; i < last; i++)
        namesSize += strlen(pTextResource->GetText(i)) + 1;
    DATA_COMPGEN_GUARD(0x005a6b04, worldDirectionNamesGuard, apNames)
    VA_COMPGEN(0x004cd704, 0x16, STATIC_DTOR, apNames)
    DATA(0x005a6ad8) static TAutoArrayPtr<char> apNames(new char[namesSize]);
    if (!apNames.get())
        throw TAllocationFailure();
    char* pName = apNames.get();
    for (i = first; i < last; i++) {
        const char* pText = pTextResource->GetText(i);
        size_t len = strlen(pText) + 1;
        memcpy(pName, pText, len);
        aWorldDirectionNamesImp[i - first] = pName;
        pName += len;
    }
}

VA(0x004cd71a, 0x94)
TWorldDirection getWorldDirection(const TTilePoint& loc, const TTilePoint& worldSize)
{
    TWorldDirection direction;
    if (loc.x() < worldSize.x() / 3) {
        if (loc.y() < worldSize.y() / 3)
            direction = eDirectionNorthWest;
        else if (loc.y() > 2 * worldSize.y() / 3)
            direction = eDirectionSouthWest;
        else
            direction = eDirectionWest;
    } else if (loc.x() > 2 * worldSize.x() / 3) {
        if (loc.y() < worldSize.y() / 3)
            direction = eDirectionNorthEast;
        else if (loc.y() > 2 * worldSize.y() / 3)
            direction = eDirectionSouthEast;
        else
            direction = eDirectionEast;
    } else {
        if (loc.y() < worldSize.y() / 3)
            direction = eDirectionNorth;
        else if (loc.y() > 2 * worldSize.y() / 3)
            direction = eDirectionSouth;
        else
            direction = eDirectionCentre;
    }
    return direction;
}
