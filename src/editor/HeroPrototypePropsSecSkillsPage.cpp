// HeroPrototypePropsSecSkillsPage.cpp - the secondary skills page of the hero prototype sheet
// (h3maped 0x456fc5..0x4573f7; GOG only). OK stores the dialog's secondary skills
// when they changed.
#include "editor/stdafx.h"

#include "exceptions.h"
#include "va.h"
#include "editor/SecondarySkillsDlg.h"
#include "editor/Hero.h"
#include "editor/HeroPrototypePropsSecSkillsPage.h"
#include "editor/MapEditorText.h"

VA(0x00457199, 0x7c)
THeroPrototypePropsSecSkillsPage::THeroPrototypePropsSecSkillsPage(const THeroPrototype& oldPrototype, THeroPrototype* pNewPrototype)
    : CPropertyPage(THeroPrototypePropsSecSkillsPage::IDD),
      _m_oldPrototype(oldPrototype),
      _m_pNewPrototype(pNewPrototype),
      _m_bModified(false)
{
    m_psp.pszTitle = m_strCaption = SHeroPrototypePropsSecSkillsPageText::kCaptionStr;
    m_psp.dwFlags |= PSP_USETITLE;
}

VA_COMPGEN(0x00457215, 0x1c, SCALAR_DELETING_DTOR, THeroPrototypePropsSecSkillsPage)

VA(0x00457231, 0x3e)
THeroPrototypePropsSecSkillsPage::~THeroPrototypePropsSecSkillsPage()
{
}

VA(0x00457272, 0x6)
BEGIN_MESSAGE_MAP(THeroPrototypePropsSecSkillsPage, CPropertyPage)
END_MESSAGE_MAP()

VA(0x00457278, 0x10a)
BOOL THeroPrototypePropsSecSkillsPage::OnInitDialog()
{
    _m_bModified = false;
    CPropertyPage::OnInitDialog();
    _m_pSecondarySkillsDlg = std::auto_ptr<TSecondarySkillsDlg>(new TSecondarySkillsDlg(this));
    if (!_m_pSecondarySkillsDlg.get())
        throw TAllocationFailure();
    CWnd* pFrame = GetDlgItem(IDC_FRAME);
    CRect rect;
    pFrame->GetWindowRect(&rect);
    ScreenToClient(&rect);
    _m_pSecondarySkillsDlg->SetWindowPos(pFrame, rect.left, rect.top, rect.Width(), rect.Height(), 0);
    pFrame->DestroyWindow();
    _m_pSecondarySkillsDlg->setSecondarySkills(_m_pNewPrototype->getSecondarySkills());
    return TRUE;
}

VA(0x00457382, 0x75)
void THeroPrototypePropsSecSkillsPage::OnOK()
{
    CPropertyPage::OnOK();
    THeroPrototype::TSecondarySkills skills = _m_pSecondarySkillsDlg->getSecondarySkills();
    if (!(skills == _m_pNewPrototype->getSecondarySkills())) {
        _m_bModified = true;
        _m_pNewPrototype->setSecondarySkills(skills);
    }
}
