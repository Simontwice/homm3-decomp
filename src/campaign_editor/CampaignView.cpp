// CampaignView.cpp - the campaign view (h3ccmped 0x41c3f0..0x41ca50).
#include "campaign_editor/stdafx.h"

#include "va.h"
#include "campaignmap.h"
#include "campaign_editor/Campaign.h"
#include "campaign_editor/CampaignDoc.h"
#include "campaign_editor/CampaignPropsDlg.h"
#include "campaign_editor/CampaignView.h"
#include "campaign_editor/resource.h"
#include "campaign_editor/ScenarioPropsSheet.h"

VA(0x0041c420, 0x57)
IMPLEMENT_DYNCREATE(TCampaignView, CView)
VA_COMPGEN(0x0041c480, 0x6, RUNTIME_CLASS_GETTER, TCampaignView)

VA(0x0041c490, 0x6)
BEGIN_MESSAGE_MAP(TCampaignView, CView)
    ON_WM_DESTROY()
    ON_WM_CREATE()
    ON_WM_SIZE()
    ON_COMMAND(ID_CAMPAIGN_PROPERTIES, OnCampaignProperties)
END_MESSAGE_MAP()

VA(0x0041c4a0, 0x28)
TCampaignView::TCampaignView()
    : _m_pStatusUI(NULL), _m_pMapWnd(NULL)
{
}

VA_COMPGEN(0x0041c4d0, 0x1e, SCALAR_DELETING_DTOR, TCampaignView)

VA(0x0041c4f0, 0x12)
TCampaignView::~TCampaignView()
{
}

VA(0x0041c510, 0x81)
BOOL TCampaignView::PreCreateWindow(CREATESTRUCT& cs)
{
    DATA_COMPGEN_GUARD(0x004c7580, classNameGuard, className)
    VA_COMPGEN(0x0041c5a0, 0xa, STATIC_DTOR, className)
    DATA(0x004c757c) static CString className;
    if (className.IsEmpty())
        className = AfxRegisterWndClass(CS_DBLCLKS, ::LoadCursor(NULL, IDC_ARROW), (HBRUSH)(COLOR_BTNFACE + 1));
    cs.lpszClass = className;
    cs.style = WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS;
    return CView::PreCreateWindow(cs);
}

VA(0x0041c5b0, 0xa)
void TCampaignView::setStatusUI(TStatusUI* pStatusUI)
{
    _m_pStatusUI = pStatusUI;
}

VA(0x0041c5c0, 0x4)
TCampaignDoc* TCampaignView::GetDocument()
{
    return (TCampaignDoc*)m_pDocument;
}

VA(0x0041c5d0, 0x24)
CSize TCampaignView::getMapSize()
{
    CSize size = _m_pMapWnd->getSize();
    return size;
}

VA(0x0041c600, 0xc)
const TCampaign* TCampaignView::getCampaign()
{
    return GetDocument()->getCampaign();
}

VA(0x0041c610, 0x85)
void TCampaignView::selectScenario(int scenario)
{
    CString name(GetDocument()->getCampaign()->getMapTraits().m_regionTraits[scenario].m_name);
    _m_pStatusUI->setScenarioName(name);
}

VA(0x0041c6a0, 0xa0)
void TCampaignView::editScenario(int scenario)
{
    TCampaignDoc* pDoc = GetDocument();
    TScenarioPropsSheet sheet(this, pDoc, scenario);
    sheet.DoModal();
    if (sheet.wasModified()) {
        pDoc->SetModifiedFlag();
        pDoc->UpdateAllViews(NULL);
    }
}

VA(0x0041c740, 0x8)
void TCampaignView::OnInitialUpdate()
{
    _m_pMapWnd->initialUpdate();
}

VA(0x0041c750, 0xb)
void TCampaignView::OnUpdate(CView* pSender, LPARAM lHint, CObject* pHint)
{
    _m_pMapWnd->update();
}

void TCampaignView::OnDraw(CDC* pDC)
{
}

VA(0x0041c760, 0xc4)
int TCampaignView::OnCreate(LPCREATESTRUCT lpCreateStruct)
{
    if (CView::OnCreate(lpCreateStruct) == -1)
        return -1;
    _m_pMapWnd = new TCampaignMapWnd(this, this);
    if (_m_pMapWnd == NULL)
        throw TAllocationFailure();
    return 0;
}

VA(0x0041c830, 0x1a)
void TCampaignView::OnDestroy()
{
    delete _m_pMapWnd;
    CView::OnDestroy();
}

VA(0x0041c850, 0x4c)
void TCampaignView::OnSize(UINT nType, int cx, int cy)
{
    CView::OnSize(nType, cx, cy);
    if (_m_pMapWnd != NULL) {
        CSize size = _m_pMapWnd->getSize();
        _m_pMapWnd->MoveWindow(0, 0, min(cx, size.cx), min(cy, size.cy));
    }
}

VA(0x0041c8a0, 0x4c)
BOOL TCampaignView::OnCmdMsg(UINT nID, int nCode, void* pExtra, AFX_CMDHANDLERINFO* pHandlerInfo)
{
    if (_m_pMapWnd != NULL && _m_pMapWnd->OnCmdMsg(nID, nCode, pExtra, pHandlerInfo))
        return TRUE;
    return CView::OnCmdMsg(nID, nCode, pExtra, pHandlerInfo);
}

VA(0x0041c8f0, 0x15e)
void TCampaignView::OnCampaignProperties()
{
    TCampaignPropsDlg dlg(this, GetDocument());
    dlg.DoModal();
}
