// ScenarioPropsSheet.cpp - the scenario properties sheet (h3ccmped
// 0x42d910..0x42e280). A map imported or removed on the general page goes
// into the campaign copy at once and the other pages follow it.
#include "campaign_editor/stdafx.h"

#include "va.h"
#include "campaign_editor/Campaign.h"
#include "campaign_editor/CampaignDoc.h"
#include "campaign_editor/CampaignEditorText.h"
#include "campaign_editor/ScenarioPropsSheet.h"

VA(0x0042d940, 0x612)
TScenarioPropsSheet::TScenarioPropsSheet(CWnd* pParent, TCampaignDoc* pDoc, int scenario)
    : CPropertySheet(kScenarioPropsSheetCaptionStr, pParent),
      _m_pDoc(pDoc),
      _m_scenario(scenario)
{
    m_psh.dwFlags |= PSH_NOAPPLYNOW;
    _m_pCampaign = std::auto_ptr<TCampaign>(new TCampaign(*pDoc->getCampaign()));
    if (_m_pCampaign.get() == NULL)
        throw TAllocationFailure();
    const TScenario& oldScenario = _m_pDoc->getCampaign()->getScenario(_m_scenario);
    TScenario& newScenario = _m_pCampaign->modifyScenario(_m_scenario);
    _m_pGeneralPage = std::auto_ptr<TScenarioPropsGeneralPage>(
        new TScenarioPropsGeneralPage(this, _m_pDoc, _m_pCampaign.get(), scenario));
    if (_m_pGeneralPage.get() == NULL)
        throw TAllocationFailure();
    _m_pProloguePage = std::auto_ptr<TScenarioPropsProloguePage>(
        new TScenarioPropsProloguePage(oldScenario, newScenario, pDoc->getVersion()));
    if (_m_pProloguePage.get() == NULL)
        throw TAllocationFailure();
    _m_pEpiloguePage = std::auto_ptr<TScenarioPropsEpiloguePage>(
        new TScenarioPropsEpiloguePage(oldScenario, newScenario, pDoc->getVersion()));
    if (_m_pEpiloguePage.get() == NULL)
        throw TAllocationFailure();
    _m_pCrossoverPage = std::auto_ptr<TScenarioPropsCrossoverPage>(
        new TScenarioPropsCrossoverPage(oldScenario, newScenario, pDoc->getVersion()));
    if (_m_pCrossoverPage.get() == NULL)
        throw TAllocationFailure();
    _m_pStartingOptionsPage = std::auto_ptr<TScenarioPropsStartingOptionsPage>(new TScenarioPropsStartingOptionsPage(
        *_m_pDoc->getCampaign(), *_m_pCampaign, _m_scenario, pDoc->getVersion()));
    if (_m_pStartingOptionsPage.get() == NULL)
        throw TAllocationFailure();
    AddPage(_m_pGeneralPage.get());
    AddPage(_m_pProloguePage.get());
    AddPage(_m_pEpiloguePage.get());
    AddPage(_m_pCrossoverPage.get());
    AddPage(_m_pStartingOptionsPage.get());
}

VA_COMPGEN(0x0042df60, 0x1e, SCALAR_DELETING_DTOR, TScenarioPropsSheet)

VA(0x0042df80, 0x163)
TScenarioPropsSheet::~TScenarioPropsSheet()
{
    RemovePage(_m_pStartingOptionsPage.get());
    RemovePage(_m_pCrossoverPage.get());
    RemovePage(_m_pEpiloguePage.get());
    RemovePage(_m_pProloguePage.get());
    RemovePage(_m_pGeneralPage.get());
}

VA(0x0042e0f0, 0x59)
bool TScenarioPropsSheet::wasModified() const
{
    return _m_pGeneralPage->wasModified() || _m_pProloguePage->wasModified() || _m_pEpiloguePage->wasModified()
           || _m_pCrossoverPage->wasModified() || _m_pStartingOptionsPage->wasModified();
}

VA(0x0042e150, 0x7e)
void TScenarioPropsSheet::setMap(std::auto_ptr<TCampaignScenarioMap> pMap)
{
    _m_pCampaign->setScenarioMap(_m_scenario, pMap);
    _m_pProloguePage->update();
    _m_pEpiloguePage->update();
    _m_pCrossoverPage->update();
    _m_pStartingOptionsPage->update();
}

VA(0x0042e1d0, 0x31)
void TScenarioPropsSheet::removeMap()
{
    _m_pCampaign->removeScenarioMap(_m_scenario);
    _m_pProloguePage->update();
    _m_pEpiloguePage->update();
    _m_pCrossoverPage->update();
    _m_pStartingOptionsPage->update();
}

VA(0x0042e210, 0x6)
BEGIN_MESSAGE_MAP(TScenarioPropsSheet, CPropertySheet)
END_MESSAGE_MAP()

VA(0x0042e220, 0x35)
int TScenarioPropsSheet::DoModal()
{
    int result = CPropertySheet::DoModal();
    if (result == IDOK && wasModified())
        *_m_pDoc->getCampaign() = *_m_pCampaign;
    return result;
}
