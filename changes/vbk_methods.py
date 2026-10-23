def verify_resource(self,item):
    from charter_quotes.vbk_query import wait_resource_query
    p=self.page
    self.stage='打开资源列表'
    p.goto(LIST_URL,wait_until='domcontentloaded')
    self.stage='按资源编号查询'
    self.dismiss_notice()
    p.get_by_role('button',name='重 置',exact=True).click()
    p.get_by_role('textbox',name='资源ID',exact=True).fill(str(item['resource_id']))
    self.stage='等待本轮查询完成并读取稳定资源表格'
    return wait_resource_query(p,item,lambda:p.get_by_role('button',name='查 询',exact=True).click(),timeout_ms=getattr(self,'query_timeout_ms',45000))

def merchant(self):
    from charter_quotes.vbk_query import StableMerchantRow
    row=self.page.get_by_role('row').filter(has_text='1572124 - 夏末初秋国际旅行社(上海)有限公司')
    return StableMerchantRow(self.page,row)

def error_reason(exc):
    if type(exc).__name__=='TargetClosedError':
        return 'VBK浏览器或页面已关闭，操作未完成；请保留浏览器窗口并重新登录后台，不自动重试保存'
    if type(exc).__name__=='TimeoutError':
        return '后台等待超时：请检查VBK登录、查询加载或公告弹窗；不是游客端报价校验失败'
    if isinstance(exc,IndexError):
        return '后台表格未完整返回，不能读取所需列；未继续保存，请重查资源列表'
    if isinstance(exc,(RuntimeError,DepartureTimeMismatch)):
        return str(exc)
    known={
        'Returned city/date/days do not match':'携程返回的城市、日期或天数不一致，未执行改价',
        'Returned package mismatch':'携程返回的小时公里套餐不一致，未执行改价',
        'Ambiguous selected package':'携程返回多个默认套餐，无法唯一确定报价',
        'Hourly aggregate absent from first page':'当前查询未返回小时包车套餐',
        'Requested exact package not offered':'当前查询未提供对应小时公里套餐',
        'Invalid price precision':'携程返回的金额格式无效',
    }
    return known.get(str(exc),'查询数据校验失败，请检查查询条件或重新获取查价会话')
