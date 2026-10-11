// HeroPropsArtifactsPage.cpp - the artifacts page of the hero property
// sheets (h3maped 0x44e2cf..0x44e89b; Loki h3maped object 15, whose page
// keeps its own list). The artifacts list takes the frame control's place
// and shows the custom artifacts, or the hero's default ones disabled.
#include "editor/stdafx.h"

#include "exceptions.h"
#include "va.h"
#include "editor/ArtifactsDlg.h"
#include "editor/Hero.h"
#include "editor/HeroPropsArtifactsPage.h"
#include "editor/MapEditorText.h"

VA(0x0044e4a3, 0xa5)
THeroPropsArtifactsPage::THeroPropsArtifactsPage(const THero* pOldHero, THero* pNewHero, EGameVersion mapVersion)
    : CPropertyPage(THeroPropsArtifactsPage::IDD),
      _m_pOldHero(pOldHero),
      _m_pNewHero(pNewHero),
      _m_mapVersion(mapVersion),
      _m_bModified(false)
{
    _m_bCustomize = FALSE;
    m_psp.pszTitle = m_strCaption = kArtifactsPageCaptionStr;
    m_psp.dwFlags |= PSP_USETITLE;
}

VA_COMPGEN(0x0044e548, 0x1c, SCALAR_DELETING_DTOR, THeroPropsArtifactsPage)

VA(0x0044e564, 0x5f)
THeroPropsArtifactsPage::~THeroPropsArtifactsPage()
{
}

VA(0x0044e5c3, 0x2f)
void THeroPropsArtifactsPage::setDefaultArtifacts(const THeroPrototype::TArtifactContainer& artifacts)
{
    _m_defaultArtifacts = artifacts;
    if (!_m_bCustomize)
        _m_pArtifactsDlg->setArtifacts(_m_defaultArtifacts);
}

VA(0x0044e5f2, 0x18)
void THeroPropsArtifactsPage::DoDataExchange(CDataExchange* pDX)
{
    DDX_Check(pDX, IDC_CUSTOMIZE_CHECK, _m_bCustomize);
}

VA(0x0044e60a, 0x6)
BEGIN_MESSAGE_MAP(THeroPropsArtifactsPage, CPropertyPage)
    ON_BN_CLICKED(IDC_CUSTOMIZE_CHECK, OnCustomizeCheck)
END_MESSAGE_MAP()

VA(0x0044e610, 0x168)
BOOL THeroPropsArtifactsPage::OnInitDialog()
{
    GetDlgItem(IDC_CUSTOMIZE_CHECK)->SetWindowText(kCustomizeCheckStr);
    _m_bModified = false;
    _m_bCustomize = _m_pNewHero->getBCustomArtifacts();
    _m_artifacts = _m_pNewHero->getArtifacts();
    CPropertyPage::OnInitDialog();
    _m_pArtifactsDlg = std::auto_ptr<TArtifactsDlg>(new TArtifactsDlg(this, _m_mapVersion));
    if (!_m_pArtifactsDlg.get())
        throw TAllocationFailure();
    CWnd* pFrame = GetDlgItem(IDC_FRAME);
    CRect rect;
    pFrame->GetWindowRect(&rect);
    ScreenToClient(&rect);
    _m_pArtifactsDlg->SetWindowPos(pFrame, rect.left, rect.top, rect.Width(), rect.Height(), 0);
    pFrame->DestroyWindow();
    _m_pArtifactsDlg->setArtifacts(_m_bCustomize ? _m_artifacts : _m_defaultArtifacts);
    if (!_m_bCustomize)
        _m_pArtifactsDlg->EnableWindow(FALSE);
    return TRUE;
}

VA(0x0044e778, 0x9d)
void THeroPropsArtifactsPage::OnOK()
{
    CPropertyPage::OnOK();
    if (_m_bCustomize)
        _m_artifacts = _m_pArtifactsDlg->getArtifacts();
    _m_pNewHero->setBCustomArtifacts(_m_bCustomize != FALSE);
    _m_pNewHero->setArtifacts(_m_artifacts);
    _m_bModified = _m_bModified || _m_pOldHero->getBCustomArtifacts() != _m_pNewHero->getBCustomArtifacts()
                   || _m_pNewHero->getArtifacts() != _m_pOldHero->getArtifacts();
}

VA(0x0044e815, 0x86)
void THeroPropsArtifactsPage::OnCustomizeCheck()
{
    bool bWasCustomized = _m_bCustomize != FALSE;
    UpdateData(TRUE);
    if (_m_bCustomize) {
        if (!bWasCustomized) {
            _m_pArtifactsDlg->EnableWindow(TRUE);
            _m_pArtifactsDlg->setArtifacts(_m_artifacts);
        }
    } else if (bWasCustomized) {
        _m_artifacts = _m_pArtifactsDlg->getArtifacts();
        _m_pArtifactsDlg->setArtifacts(_m_defaultArtifacts);
        _m_pArtifactsDlg->EnableWindow(FALSE);
    }
}
