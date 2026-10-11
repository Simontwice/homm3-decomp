// HeroPrototypePropsArtifactsPage.cpp - the artifacts page of the hero
// prototype sheet (h3maped 0x45527a..0x4556bd; GOG only). OK stores the
// list's artifacts when they changed.
#include "editor/stdafx.h"

#include "exceptions.h"
#include "va.h"
#include "editor/ArtifactsDlg.h"
#include "editor/Hero.h"
#include "editor/HeroPrototypePropsArtifactsPage.h"
#include "editor/MapEditorText.h"

VA(0x0045544e, 0x85)
THeroPrototypePropsArtifactsPage::THeroPrototypePropsArtifactsPage(const THeroPrototype& oldPrototype,
                                                                   THeroPrototype* pNewPrototype,
                                                                   EGameVersion mapVersion)
    : CPropertyPage(THeroPrototypePropsArtifactsPage::IDD),
      _m_oldPrototype(oldPrototype),
      _m_pNewPrototype(pNewPrototype),
      _m_mapVersion(mapVersion),
      _m_bModified(false)
{
    m_psp.pszTitle = m_strCaption = SHeroPrototypePropsArtifactsPageText::kCaptionStr;
    m_psp.dwFlags |= PSP_USETITLE;
}

VA_COMPGEN(0x004554d3, 0x1c, SCALAR_DELETING_DTOR, THeroPrototypePropsArtifactsPage)

VA(0x004554ef, 0x3e)
THeroPrototypePropsArtifactsPage::~THeroPrototypePropsArtifactsPage()
{
}

VA(0x0045552d, 0x6)
BEGIN_MESSAGE_MAP(THeroPrototypePropsArtifactsPage, CPropertyPage)
END_MESSAGE_MAP()

VA(0x00455533, 0x110)
BOOL THeroPrototypePropsArtifactsPage::OnInitDialog()
{
    _m_bModified = false;
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
    _m_pArtifactsDlg->setArtifacts(_m_pNewPrototype->getArtifacts());
    return TRUE;
}

VA(0x00455643, 0x7a)
void THeroPrototypePropsArtifactsPage::OnOK()
{
    CPropertyPage::OnOK();
    THeroPrototype::TArtifactContainer artifacts(_m_pArtifactsDlg->getArtifacts());
    if (artifacts != _m_pNewPrototype->getArtifacts()) {
        _m_bModified = true;
        _m_pNewPrototype->setArtifacts(artifacts);
    }
}
