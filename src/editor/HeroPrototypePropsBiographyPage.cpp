// HeroPrototypePropsBiographyPage.cpp - the biography page of the hero
// prototype sheet (h3maped 0x4556bd..0x455aee; GOG only). The prototype
// keeps LF line ends, the edit CR LF.
#include "editor/stdafx.h"

#include <string>

#include "va.h"
#include "editor/Hero.h"
#include "editor/HeroPrototypePropsBiographyPage.h"
#include "editor/MapEditorText.h"

VA(0x00455891, 0x85)
THeroPrototypePropsBiographyPage::THeroPrototypePropsBiographyPage(const THeroPrototype& oldPrototype,
                                                                   THeroPrototype* pNewPrototype)
    : CPropertyPage(THeroPrototypePropsBiographyPage::IDD),
      _m_oldPrototype(oldPrototype),
      _m_pNewPrototype(pNewPrototype),
      _m_bModified(false)
{
    m_psp.pszTitle = m_strCaption = SHeroPrototypePropsBiographyPageText::kCaptionStr;
    m_psp.dwFlags |= PSP_USETITLE;
}

VA_COMPGEN(0x00455916, 0x1c, SCALAR_DELETING_DTOR, THeroPrototypePropsBiographyPage)

VA(0x00455932, 0x3e)
THeroPrototypePropsBiographyPage::~THeroPrototypePropsBiographyPage()
{
}

VA(0x00455970, 0x18)
void THeroPrototypePropsBiographyPage::DoDataExchange(CDataExchange* pDX)
{
    DDX_Control(pDX, IDC_BIOGRAPHY_EDIT, _m_biographyEdit);
}

VA(0x00455988, 0x6)
BEGIN_MESSAGE_MAP(THeroPrototypePropsBiographyPage, CPropertyPage)
END_MESSAGE_MAP()

VA(0x0045598e, 0x7a)
BOOL THeroPrototypePropsBiographyPage::OnInitDialog()
{
    _m_bModified = false;
    CPropertyPage::OnInitDialog();
    CString biography(_m_pNewPrototype->getBiography().c_str());
    biography.Replace("\n", "\r\n");
    _m_biographyEdit.SetWindowText(biography);
    return TRUE;
}

VA(0x00455a08, 0xc3)
void THeroPrototypePropsBiographyPage::OnOK()
{
    CPropertyPage::OnOK();
    CString biography;
    _m_biographyEdit.GetWindowText(biography);
    biography.Replace("\r\n", "\n");
    if ((LPCTSTR)biography != _m_pNewPrototype->getBiography()) {
        _m_bModified = true;
        _m_pNewPrototype->setBiography(std::string(biography));
    }
}
