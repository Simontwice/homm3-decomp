// HeroPrototypePropsSheet.cpp - the properties sheet of one hero's map
// definition (h3maped 0x4573f7..0x457c1a; GOG only). The pages edit a copy
// of the map's prototype; the players on the map may hire the hero.
#include "editor/stdafx.h"

#include "exceptions.h"
#include "va.h"
#include "editor/HeroPrototypePropsArtifactsPage.h"
#include "editor/HeroPrototypePropsBiographyPage.h"
#include "editor/HeroPrototypePropsPriSkillsPage.h"
#include "editor/HeroPrototypePropsSecSkillsPage.h"
#include "editor/HeroPrototypePropsSheet.h"
#include "editor/HeroPrototypePropsSpellsPage.h"
#include "editor/MapEditorText.h"

VA(0x004575cb, 0x466)
THeroPrototypePropsSheet::THeroPrototypePropsSheet(CWnd* pParentWnd, TGameMap& gameMap, THeroID heroID)
    : CPropertySheet(SHeroPrototypePropsSheetText::kCaptionStr, pParentWnd),
      _m_map(gameMap),
      _m_heroID(heroID),
      _m_prototype(gameMap.getHeroPrototype(heroID)),
      _m_numOKDisablers(0)
{
    m_psh.dwFlags |= PSH_NOAPPLYNOW;
    const THeroPrototype& oldPrototype = _m_map.getHeroPrototype(_m_heroID);
    TPlayerMask playersPresent;
    for (int player = 0; player < kNumPlayers; player++)
        playersPresent[player] = _m_map.isPlayerPresent(TPlayer(player));
    _m_pGeneralPage = std::auto_ptr<THeroPrototypePropsGeneralPage>(
        new THeroPrototypePropsGeneralPage(this, _m_heroID, oldPrototype, &_m_prototype, playersPresent));
    if (!_m_pGeneralPage.get())
        throw TAllocationFailure();
    _m_pBiographyPage = std::auto_ptr<THeroPrototypePropsBiographyPage>(
        new THeroPrototypePropsBiographyPage(oldPrototype, &_m_prototype));
    if (!_m_pBiographyPage.get())
        throw TAllocationFailure();
    _m_pPriSkillsPage = std::auto_ptr<THeroPrototypePropsPriSkillsPage>(
        new THeroPrototypePropsPriSkillsPage(oldPrototype, &_m_prototype));
    if (!_m_pPriSkillsPage.get())
        throw TAllocationFailure();
    _m_pSecSkillsPage = std::auto_ptr<THeroPrototypePropsSecSkillsPage>(
        new THeroPrototypePropsSecSkillsPage(oldPrototype, &_m_prototype));
    if (!_m_pSecSkillsPage.get())
        throw TAllocationFailure();
    _m_pArtifactsPage = std::auto_ptr<THeroPrototypePropsArtifactsPage>(
        new THeroPrototypePropsArtifactsPage(oldPrototype, &_m_prototype, _m_map.getVersion()));
    if (!_m_pArtifactsPage.get())
        throw TAllocationFailure();
    _m_pSpellsPage = std::auto_ptr<THeroPrototypePropsSpellsPage>(
        new THeroPrototypePropsSpellsPage(oldPrototype, &_m_prototype, _m_map.getVersion()));
    // Retail tests the artifacts page again here.
    if (!_m_pArtifactsPage.get())
        throw TAllocationFailure();
    AddPage(_m_pGeneralPage.get());
    AddPage(_m_pBiographyPage.get());
    AddPage(_m_pPriSkillsPage.get());
    AddPage(_m_pSecSkillsPage.get());
    AddPage(_m_pArtifactsPage.get());
    AddPage(_m_pSpellsPage.get());
}

VA_COMPGEN(0x00457a31, 0x1c, SCALAR_DELETING_DTOR, THeroPrototypePropsSheet)

VA(0x00457a4d, 0xf5)
THeroPrototypePropsSheet::~THeroPrototypePropsSheet()
{
    RemovePage(_m_pSpellsPage.get());
    RemovePage(_m_pArtifactsPage.get());
    RemovePage(_m_pSecSkillsPage.get());
    RemovePage(_m_pPriSkillsPage.get());
    RemovePage(_m_pBiographyPage.get());
    RemovePage(_m_pGeneralPage.get());
}

VA(0x00457b42, 0x5a)
bool THeroPrototypePropsSheet::wasModified() const
{
    return _m_pGeneralPage->wasModified() || _m_pBiographyPage->wasModified() || _m_pPriSkillsPage->wasModified()
           || _m_pSecSkillsPage->wasModified() || _m_pArtifactsPage->wasModified() || _m_pSpellsPage->wasModified();
}

VA(0x00457b9c, 0x1c)
void THeroPrototypePropsSheet::onEnableOK()
{
    if (--_m_numOKDisablers == 0) {
        CWnd* pOKButton = GetDlgItem(IDOK);
        pOKButton->EnableWindow(TRUE);
    }
}

VA(0x00457bb8, 0x24)
void THeroPrototypePropsSheet::onDisableOK()
{
    if (_m_numOKDisablers++ == 0) {
        CWnd* pOKButton = GetDlgItem(IDOK);
        pOKButton->EnableWindow(FALSE);
    }
}

VA(0x00457bdc, 0x6)
BEGIN_MESSAGE_MAP(THeroPrototypePropsSheet, CPropertySheet)
END_MESSAGE_MAP()

VA(0x00457be2, 0x38)
int THeroPrototypePropsSheet::DoModal()
{
    int result = CPropertySheet::DoModal();
    if (result == IDOK && wasModified())
        _m_map.setHeroPrototype(_m_heroID, _m_prototype);
    return result;
}
