from datetime import datetime

def days_from_date(target_date_str, date_format="%Y-%m-%d"):
    """
    计算某个日期到今天的天数差
    
    参数:
    target_date_str: 目标日期字符串
    date_format: 日期格式，默认为"YYYY-MM-DD"
    
    返回:
    天数差（整数），如果目标日期在今天之后返回正数，在今天之前返回负数
    """
    # 今天的日期
    today = datetime.now().date()
    
    try:
        # 解析输入的日期
        target_date = datetime.strptime(target_date_str, date_format).date()
        
        # 计算天数差
        delta = (today - target_date).days
        
        return delta + 1
    except ValueError as e:
        raise ValueError(f"日期格式错误，请确保日期格式为 {date_format}。错误: {e}")

# 使用示例
if __name__ == "__main__":
    start_day_str = "2025-05-06"
    result = days_from_date(start_day_str)
    # 需要减去的天数，漏服
    subtract_days = 5 
    # 需要增加的天数，丢失
    add_days = 1
    print(f"{start_day_str} 到今天的天数差: {result} 天,距离下一个30天周期还有{(result+add_days-subtract_days) % 30 - 30}天")