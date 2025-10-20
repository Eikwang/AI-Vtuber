import json
import os
import re

def clean_text(text):
    """清理文本，移除不必要的空格和特殊字符"""
    # 移除多余的空格和换行
    text = re.sub(r'\s+', ' ', text.strip())
    return text

def detect_qa_format(lines):
    """检测问答格式"""
    prefixed_lines = 0
    total_content_lines = 0
    
    # 支持的前缀格式
    question_prefixes = ['问:', 'Q:', 'q:', '问：', 'Q：', 'q：']
    answer_prefixes = ['答:', 'A:', 'a:', '答：', 'A：', 'a：']
    
    for line in lines:
        if line.strip():
            total_content_lines += 1
            # 检查是否有任何支持的前缀
            has_prefix = any(line.startswith(prefix) for prefix in question_prefixes + answer_prefixes)
            if has_prefix:
                prefixed_lines += 1
    
    if total_content_lines == 0:
        return "empty"
    
    prefix_ratio = prefixed_lines / total_content_lines
    
    if prefix_ratio > 0.8:
        return "prefixed"  # 大部分都有前缀
    elif prefix_ratio > 0.3:
        return "mixed"     # 混合格式
    else:
        return "alternating"  # 交替格式

def parse_prefixed_format(lines):
    """解析前缀格式（问:、答:、Q:、A: 等）"""
    conversations = []
    current_question = None
    current_answer = None
    
    # 支持的前缀格式
    question_prefixes = ['问:', 'Q:', 'q:', '问：', 'Q：', 'q：']
    answer_prefixes = ['答:', 'A:', 'a:', '答：', 'A：', 'a：']
    
    def remove_prefix(text, prefixes):
        """移除匹配的前缀并返回处理后的文本"""
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text
    
    def is_question_line(text):
        """判断是否是问题行"""
        return any(text.startswith(prefix) for prefix in question_prefixes)
    
    def is_answer_line(text):
        """判断是否是答案行"""
        return any(text.startswith(prefix) for prefix in answer_prefixes)
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if is_question_line(line):
            # 如果有未完成的问答对，先保存
            if current_question and current_answer:
                conversations.append([clean_text(current_question), clean_text(current_answer)])
            
            current_question = remove_prefix(line, question_prefixes)
            current_answer = None
            
        elif is_answer_line(line):
            if current_question:
                current_answer = remove_prefix(line, answer_prefixes)
                conversations.append([clean_text(current_question), clean_text(current_answer)])
                current_question = None
                current_answer = None
    
    return conversations

def parse_mixed_format(lines):
    """解析混合格式"""
    conversations = []
    content_lines = []
    
    # 支持的前缀格式
    all_prefixes = ['问:', 'Q:', 'q:', '问：', 'Q：', 'q：', '答:', 'A:', 'a:', '答：', 'A：', 'a：']
    
    def remove_any_prefix(text):
        """移除任何匹配的前缀"""
        for prefix in all_prefixes:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text
    
    # 先收集所有非空行
    for line in lines:
        line = line.strip()
        if line:
            # 清除所有可能的前缀
            cleaned_line = remove_any_prefix(line)
            
            if cleaned_line:  # 确保清除后仍有内容
                content_lines.append(cleaned_line)
    
    # 按顺序两两配对
    for i in range(0, len(content_lines), 2):
        if i + 1 < len(content_lines):
            question = clean_text(content_lines[i])
            answer = clean_text(content_lines[i + 1])
            if question and answer:
                conversations.append([question, answer])
    
    return conversations

def parse_alternating_format(lines):
    """解析交替格式（问题和答案交替出现）"""
    return parse_mixed_format(lines)  # 使用相同的逻辑

def txt_to_json(txt_file_path):
    """
    智能转换TXT问答文件为ChatterBot所需的JSON格式
    支持多种文本格式：
    1. 前缀格式：问: 和 答:、Q: 和 A:（支持中英文、冒号/全角冒号、大小写）
    2. 混合格式：部分有前缀，部分没有
    3. 交替格式：问题和答案交替出现
    
    支持的前缀格式：
    - 中文：问: 答: 问： 答：
    - 英文：Q: A: q: a: Q： A： q： a：
    """
    # 提取文件名作为categories
    file_name = os.path.splitext(os.path.basename(txt_file_path))[0]
    
    try:
        # 读取文件
        with open(txt_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        if not lines:
            print(f"警告: 文件 {file_name} 为空")
            return
        
        # 检测文本格式
        format_type = detect_qa_format(lines)
        print(f"检测到文件 {file_name} 的格式类型: {format_type}")
        if format_type == "prefixed":
            print(f"  → 使用前缀格式解析（支持：问:/答:, Q:/A: 等）")
        elif format_type == "mixed":
            print(f"  → 使用混合格式解析（自动去除各种前缀）")
        else:
            print(f"  → 使用交替格式解析")
        
        # 根据格式类型选择解析方法
        if format_type == "empty":
            print(f"警告: 文件 {file_name} 没有有效内容")
            return
        elif format_type == "prefixed":
            conversations = parse_prefixed_format(lines)
        elif format_type == "mixed":
            conversations = parse_mixed_format(lines)
        else:  # alternating
            conversations = parse_alternating_format(lines)
        
        # 验证转换结果
        if not conversations:
            print(f"警告: 文件 {file_name} 未能解析出有效的问答对")
            return
        
        # 过滤无效对话
        valid_conversations = []
        for conv in conversations:
            if len(conv) == 2 and conv[0] and conv[1]:
                # 检查最小长度
                if len(conv[0]) >= 2 and len(conv[1]) >= 2:
                    valid_conversations.append(conv)
        
        if not valid_conversations:
            print(f"警告: 文件 {file_name} 没有有效的问答对")
            return
        
        # 构建 JSON 数据结构
        json_data = {
            "categories": [file_name],
            "conversations": valid_conversations
        }
        
        # 生成输出JSON文件路径
        json_file_path = os.path.splitext(txt_file_path)[0] + '.json'
        
        # 保存为JSON文件
        with open(json_file_path, 'w', encoding='utf-8') as file:
            json.dump(json_data, file, ensure_ascii=False, indent=4)
        
        print(f"✓ 转换成功: {txt_file_path} -> {json_file_path}")
        print(f"  原文件行数: {len(lines)}, 转换得到: {len(valid_conversations)} 组有效问答对")
        
        # 显示前几个示例
        print("  示例问答对:")
        for i, conv in enumerate(valid_conversations[:3]):
            print(f"    {i+1}. Q: {conv[0][:50]}{'...' if len(conv[0]) > 50 else ''}")
            print(f"       A: {conv[1][:50]}{'...' if len(conv[1]) > 50 else ''}")
        
        if len(valid_conversations) > 3:
            print(f"    ... 还有 {len(valid_conversations) - 3} 组")
        
        print()
        
    except Exception as e:
        print(f"错误: 无法处理文件 {txt_file_path}: {e}")

def validate_json_file(json_file_path):
    """验证JSON文件的有效性"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        
        if 'conversations' not in data:
            return False, "缺少 'conversations' 字段"
        
        if not isinstance(data['conversations'], list):
            return False, "'conversations' 字段不是列表"
        
        valid_count = 0
        for i, conv in enumerate(data['conversations']):
            if not isinstance(conv, list) or len(conv) < 2:
                continue
            if conv[0] and conv[1]:
                valid_count += 1
        
        if valid_count == 0:
            return False, "没有有效的问答对"
        
        return True, f"有效, 包含 {valid_count} 组问答对"
        
    except Exception as e:
        return False, f"解析错误: {e}"

def batch_convert(data_dir="./data"):
    """
    批量转换指定目录及其所有子目录下的所有TXT文件
    支持智能格式检测和多种问答文本格式
    
    支持的前缀格式：
    - 中文：问: 答: 问： 答：
    - 英文：Q: A: q: a: Q： A： q： a：
    - 混合格式和交替格式
    """
    print(f"=== 智能 TXT 转 JSON 工具（增强版）===")
    print(f"支持格式：问:/答:, Q:/A:, q:/a:, 问：/答：, Q：/A：, q：/a：")
    print(f"扫描目录: {os.path.abspath(data_dir)}")
    
    # 检查目录是否存在
    if not os.path.exists(data_dir):
        print(f"错误: 目录 {data_dir} 不存在，请创建该目录并放入TXT文件后重试")
        return
    
    # 递归遍历所有目录和子目录
    txt_files = []
    json_files = []
    
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith('.txt'):
                txt_files.append(os.path.join(root, f))
            elif f.endswith('.json'):
                json_files.append(os.path.join(root, f))
    
    print(f"找到 {len(txt_files)} 个 TXT 文件, {len(json_files)} 个现有 JSON 文件")
    
    if not txt_files:
        print(f"提示: 目录 {data_dir} 及其子目录中没有找到TXT文件")
        
        # 验证现有的JSON文件
        if json_files:
            print("\n验证现有的JSON文件:")
            for json_file in json_files:
                is_valid, message = validate_json_file(json_file)
                status = "✓" if is_valid else "✗"
                print(f"  {status} {os.path.basename(json_file)}: {message}")
        return
    
    # 逐个转换TXT文件
    success_count = 0
    
    for txt_file in txt_files:
        print(f"\n处理: {os.path.basename(txt_file)}")
        try:
            txt_to_json(txt_file)
            success_count += 1
        except Exception as e:
            print(f"错误: 无法转换 {txt_file}: {e}")
    
    # 总结
    print(f"\n=== 转换完成（增强版）===")
    print(f"成功转换: {success_count}/{len(txt_files)} 个文件")
    print(f"支持的前缀格式已全面升级：问:/答:, Q:/A:, q:/a:, 问：/答：, Q：/A：, q：/a：")
    
    # 验证转换结果
    if success_count > 0:
        print("\n验证转换结果:")
        for root, dirs, files in os.walk(data_dir):
            for f in files:
                if f.endswith('.json'):
                    json_file = os.path.join(root, f)
                    is_valid, message = validate_json_file(json_file)
                    status = "✓" if is_valid else "✗"
                    print(f"  {status} {os.path.basename(json_file)}: {message}")

if __name__ == "__main__":
    print("TXT转JSON增强工具 - 支持多种前缀格式")
    print("支持：问:/答:, Q:/A:, q:/a:, 问：/答：, Q：/A：, q：/a：")
    print("="*50)
    # 执行批量转换
    batch_convert()