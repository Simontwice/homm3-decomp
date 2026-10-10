// QuestGuardPropsDlg.cpp - the Quest Guard's properties dialog (h3maped
// 0x495de9..0x496124; GOG only).
#include "editor/stdafx.h"

#include "exceptions.h"
#include "va.h"
#include "editor/GameMap.h"
#include "editor/QuestGuardPropsDlg.h"

enum { kQuestGuardTextColumn = 4 };

VA(0x00495fbd, 0xe1)
TQuestGuardPropsDlg::TQuestGuardPropsDlg(CWnd* pParent, TGameMap* pMap, bool bSecondLayer, unsigned int objID)
    : TQuestLocationPropsDlg(TQuestGuardPropsDlg::IDD, pParent, pMap, bSecondLayer, objID, kQuestGuardTextColumn),
      _m_pMap(pMap)
{
    _m_pNewMap = std::auto_ptr<TGameMap>(new TGameMap(*_m_pMap));
    if (!_m_pNewMap.get())
        throw TAllocationFailure();
    _setNewMap(_m_pNewMap.get());
}

VA_COMPGEN(0x0049609e, 0x1c, SCALAR_DELETING_DTOR, TQuestGuardPropsDlg)

VA(0x004960ba, 0x3e)
TQuestGuardPropsDlg::~TQuestGuardPropsDlg()
{
}

VA(0x004960f8, 0x2c)
int TQuestGuardPropsDlg::DoModal()
{
    int result = CDialog::DoModal();
    if (result == IDOK && wasModified())
        *_m_pMap = *_m_pNewMap;
    return result;
}
