// HeroPrototypePropsSpellsPage.cpp - the spells page of the hero prototype sheet
// (h3maped 0x457c1a..0x45802b; GOG only). OK stores the dialog's spells
// when they changed.
#include "editor/stdafx.h"

#include "exceptions.h"
#include "va.h"
#include "editor/SpellsDlg.h"
#include "editor/Hero.h"
#include "editor/HeroPrototypePropsSpellsPage.h"
#include "editor/MapEditorText.h"

VA(0x00457dee, 0x85)
THeroPrototypePropsSpellsPage::THeroPrototypePropsSpellsPage(const THeroPrototype& oldPrototype, THeroPrototype* pNewPrototype, EGameVersion mapVersion)
    : CPropertyPage(THeroPrototypePropsSpellsPage::IDD),
      _m_oldPrototype(oldPrototype),
      _m_pNewPrototype(pNewPrototype),
      _m_mapVersion(mapVersion),
      _m_bModified(false)
{
    m_psp.pszTitle = m_strCaption = SHeroPrototypePropsSpellsPageText::kCaptionStr;
    m_psp.dwFlags |= PSP_USETITLE;
}

VA_COMPGEN(0x00457e73, 0x1c, SCALAR_DELETING_DTOR, THeroPrototypePropsSpellsPage)

VA(0x00457e8f, 0x3e)
THeroPrototypePropsSpellsPage::~THeroPrototypePropsSpellsPage()
{
}

VA(0x00457ecd, 0x6)
BEGIN_MESSAGE_MAP(THeroPrototypePropsSpellsPage, CPropertyPage)
END_MESSAGE_MAP()

VA(0x00457ed3, 0x106)
BOOL THeroPrototypePropsSpellsPage::OnInitDialog()
{
    CPropertyPage::OnInitDialog();
    _m_pSpellsDlg = std::auto_ptr<TSpellsDlg>(new TSpellsDlg(this, _m_mapVersion));
    if (!_m_pSpellsDlg.get())
        throw TAllocationFailure();
    CWnd* pFrame = GetDlgItem(IDC_FRAME);
    CRect rect;
    pFrame->GetWindowRect(&rect);
    ScreenToClient(&rect);
    _m_pSpellsDlg->SetWindowPos(pFrame, rect.left, rect.top, rect.Width(), rect.Height(), 0);
    pFrame->DestroyWindow();
    _m_pSpellsDlg->setSpells(_m_pNewPrototype->getSpells());
    return TRUE;
}

VA(0x00457fd9, 0x52)
void THeroPrototypePropsSpellsPage::OnOK()
{
    CPropertyPage::OnOK();
    THeroPrototype::TSpells spells(_m_pSpellsDlg->getSpells());
    if (spells != _m_pNewPrototype->getSpells()) {
        _m_bModified = true;
        _m_pNewPrototype->setSpells(spells);
    }
}
