"""
ChatterBot 数据质量检查和优化工具
用于分析训练数据的质量，并提供改进建议
"""

import json
import os
from collections import Counter, defaultdict
import re

def analyze_conversation_quality(conversations):
    """分析对话质量"""
    quality_report = {
        'total_pairs': len(conversations),
        'avg_question_length': 0,
        'avg_answer_length': 0,
        'short_questions': 0,
        'short_answers': 0,
        'long_questions': 0,
        'long_answers': 0,
        'duplicate_questions': 0,
        'similar_questions': 0,
        'question_types': Counter(),
        'answer_patterns': Counter(),
        'issues': []
    }
    
    if not conversations:
        return quality_report
    
    question_lengths = []
    answer_lengths = []
    questions = []
    answers = []
    
    # 分析每个对话对
    for conv in conversations:
        if len(conv) >= 2:
            question = conv[0].strip()
            answer = conv[1].strip()
            
            questions.append(question)
            answers.append(answer)
            
            question_lengths.append(len(question))
            answer_lengths.append(len(answer))
            
            # 检查过短的问题和答案
            if len(question) < 3:
                quality_report['short_questions'] += 1
            if len(answer) < 3:
                quality_report['short_answers'] += 1
            
            # 检查过长的问题和答案
            if len(question) > 100:
                quality_report['long_questions'] += 1
            if len(answer) > 200:
                quality_report['long_answers'] += 1
            
            # 分析问题类型
            if question.endswith('？') or question.endswith('?'):
                quality_report['question_types']['疑问句'] += 1
            elif any(word in question for word in ['是什么', '什么是', '怎么', '如何', '为什么']):
                quality_report['question_types']['询问类'] += 1
            elif any(word in question for word in ['你好', '您好', '谢谢', '再见']):
                quality_report['question_types']['礼貌用语'] += 1
            else:
                quality_report['question_types']['其他'] += 1
            
            # 分析答案模式
            if len(answer) < 20:
                quality_report['answer_patterns']['简短回答'] += 1
            elif len(answer) < 50:
                quality_report['answer_patterns']['中等回答'] += 1
            else:
                quality_report['answer_patterns']['详细回答'] += 1
    
    # 计算平均长度
    if question_lengths:
        quality_report['avg_question_length'] = sum(question_lengths) / len(question_lengths)
    if answer_lengths:
        quality_report['avg_answer_length'] = sum(answer_lengths) / len(answer_lengths)
    
    # 检查重复问题
    question_counts = Counter(questions)
    quality_report['duplicate_questions'] = sum(1 for count in question_counts.values() if count > 1)
    
    # 检查相似问题（简单的相似度检查）
    similar_pairs = 0
    for i, q1 in enumerate(questions):
        for j, q2 in enumerate(questions[i+1:], i+1):
            if calculate_simple_similarity(q1, q2) > 0.8:
                similar_pairs += 1
    quality_report['similar_questions'] = similar_pairs
    
    # 生成问题报告
    issues = []
    if quality_report['short_questions'] > quality_report['total_pairs'] * 0.1:
        issues.append(f"过多的短问题: {quality_report['short_questions']} 个")
    if quality_report['short_answers'] > quality_report['total_pairs'] * 0.1:
        issues.append(f"过多的短答案: {quality_report['short_answers']} 个")
    if quality_report['duplicate_questions'] > 0:
        issues.append(f"存在重复问题: {quality_report['duplicate_questions']} 个")
    if quality_report['similar_questions'] > quality_report['total_pairs'] * 0.05:
        issues.append(f"相似问题过多: {quality_report['similar_questions']} 对")
    
    quality_report['issues'] = issues
    
    return quality_report

def calculate_simple_similarity(text1, text2):
    """计算两个文本的简单相似度"""
    # 移除标点符号并转为小写
    text1 = re.sub(r'[^\w\s]', '', text1.lower())
    text2 = re.sub(r'[^\w\s]', '', text2.lower())
    
    # 计算词汇重叠度
    words1 = set(text1.split())
    words2 = set(text2.split())
    
    if not words1 and not words2:
        return 1.0
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    
    return intersection / union if union > 0 else 0.0

def suggest_improvements(quality_report):
    """基于质量报告提供改进建议"""
    suggestions = []
    
    if quality_report['short_questions'] > 0:
        suggestions.append(f"建议扩展 {quality_report['short_questions']} 个过短的问题，使其更加具体和明确。")
    
    if quality_report['short_answers'] > 0:
        suggestions.append(f"建议丰富 {quality_report['short_answers']} 个过短的答案，提供更详细的信息。")
    
    if quality_report['duplicate_questions'] > 0:
        suggestions.append(f"建议合并或删除 {quality_report['duplicate_questions']} 个重复的问题。")
    
    if quality_report['similar_questions'] > 0:
        suggestions.append(f"建议检查 {quality_report['similar_questions']} 对相似的问题，确保答案一致性。")
    
    # 分析问题类型分布
    question_types = quality_report['question_types']
    total_questions = sum(question_types.values())
    
    if total_questions > 0:
        inquiry_ratio = question_types.get('询问类', 0) / total_questions
        greeting_ratio = question_types.get('礼貌用语', 0) / total_questions
        
        if inquiry_ratio < 0.3:
            suggestions.append("建议增加更多询问类问题（如'是什么'、'怎么'等）以提高实用性。")
        
        if greeting_ratio < 0.1:
            suggestions.append("建议增加基本的礼貌用语问答以改善用户体验。")
    
    # 分析答案长度分布
    answer_patterns = quality_report['answer_patterns']
    total_answers = sum(answer_patterns.values())
    
    if total_answers > 0:
        short_ratio = answer_patterns.get('简短回答', 0) / total_answers
        detailed_ratio = answer_patterns.get('详细回答', 0) / total_answers
        
        if short_ratio > 0.7:
            suggestions.append("建议增加更多详细的回答以提供更有价值的信息。")
        elif detailed_ratio > 0.8:
            suggestions.append("可以考虑简化一些过于详细的回答，提高响应效率。")
    
    return suggestions

def analyze_corpus_file(file_path):
    """分析单个语料文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'conversations' not in data:
            return None, "文件格式错误：缺少 'conversations' 字段"
        
        conversations = data['conversations']
        quality_report = analyze_conversation_quality(conversations)
        suggestions = suggest_improvements(quality_report)
        
        return {
            'file_path': file_path,
            'quality_report': quality_report,
            'suggestions': suggestions
        }, None
        
    except Exception as e:
        return None, f"分析文件时出错: {e}"

def generate_quality_report(data_dir="./data"):
    """生成完整的数据质量报告"""
    print("=== ChatterBot 数据质量分析报告 ===\n")
    
    if not os.path.exists(data_dir):
        print(f"错误: 目录 {data_dir} 不存在")
        return
    
    # 找到所有JSON文件
    json_files = []
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith('.json'):
                json_files.append(os.path.join(root, f))
    
    if not json_files:
        print(f"在目录 {data_dir} 中未找到JSON文件")
        return
    
    print(f"找到 {len(json_files)} 个JSON文件，开始分析...\n")
    
    total_quality_report = {
        'total_files': len(json_files),
        'valid_files': 0,
        'total_conversations': 0,
        'total_issues': 0,
        'file_reports': []
    }
    
    # 分析每个文件
    for json_file in json_files:
        print(f"分析文件: {os.path.basename(json_file)}")
        print("-" * 50)
        
        result, error = analyze_corpus_file(json_file)
        
        if error:
            print(f"✗ 错误: {error}\n")
            continue
        
        total_quality_report['valid_files'] += 1
        total_quality_report['total_conversations'] += result['quality_report']['total_pairs']
        total_quality_report['total_issues'] += len(result['quality_report']['issues'])
        total_quality_report['file_reports'].append(result)
        
        # 显示文件分析结果
        quality = result['quality_report']
        print(f"✓ 对话对数量: {quality['total_pairs']}")
        print(f"✓ 平均问题长度: {quality['avg_question_length']:.1f} 字符")
        print(f"✓ 平均答案长度: {quality['avg_answer_length']:.1f} 字符")
        
        # 显示问题类型分布
        if quality['question_types']:
            print("✓ 问题类型分布:")
            for qtype, count in quality['question_types'].most_common():
                percentage = count / quality['total_pairs'] * 100
                print(f"   - {qtype}: {count} 个 ({percentage:.1f}%)")
        
        # 显示质量问题
        if quality['issues']:
            print("⚠ 发现的问题:")
            for issue in quality['issues']:
                print(f"   - {issue}")
        else:
            print("✓ 未发现明显质量问题")
        
        # 显示改进建议
        if result['suggestions']:
            print("💡 改进建议:")
            for suggestion in result['suggestions']:
                print(f"   - {suggestion}")
        
        print()
    
    # 生成总体报告
    print("=" * 60)
    print("总体质量报告")
    print("=" * 60)
    print(f"✓ 分析了 {total_quality_report['valid_files']}/{total_quality_report['total_files']} 个有效文件")
    print(f"✓ 总对话对数: {total_quality_report['total_conversations']}")
    print(f"⚠ 总质量问题数: {total_quality_report['total_issues']}")
    
    if total_quality_report['total_conversations'] > 0:
        avg_quality_score = max(0, 100 - (total_quality_report['total_issues'] / total_quality_report['total_conversations'] * 100))
        print(f"📊 整体质量评分: {avg_quality_score:.1f}/100")
        
        if avg_quality_score >= 80:
            print("✅ 数据质量良好，可以开始训练")
        elif avg_quality_score >= 60:
            print("⚡ 数据质量一般，建议先进行一些优化")
        else:
            print("❌ 数据质量较差，强烈建议先优化数据再训练")
    
    # 给出总体建议
    print("\n🎯 总体优化建议:")
    if total_quality_report['total_conversations'] < 100:
        print("   - 增加更多的训练数据以提高模型性能")
    if total_quality_report['total_issues'] > total_quality_report['total_conversations'] * 0.1:
        print("   - 优先解决数据质量问题")
    print("   - 确保问答对的多样性和相关性")
    print("   - 定期更新和维护训练数据")

def find_duplicate_questions(data_dir="./data"):
    """查找重复的问题"""
    all_questions = defaultdict(list)
    
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith('.json'):
                file_path = os.path.join(root, f)
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        data = json.load(file)
                        if 'conversations' in data:
                            for i, conv in enumerate(data['conversations']):
                                if len(conv) >= 2:
                                    question = conv[0].strip()
                                    all_questions[question].append({
                                        'file': os.path.basename(file_path),
                                        'index': i,
                                        'answer': conv[1].strip()
                                    })
                except Exception as e:
                    print(f"读取文件 {file_path} 时出错: {e}")
    
    # 找出重复的问题
    duplicates = {q: occurrences for q, occurrences in all_questions.items() if len(occurrences) > 1}
    
    if duplicates:
        print("=== 重复问题报告 ===")
        print(f"发现 {len(duplicates)} 个重复的问题:\n")
        
        for question, occurrences in duplicates.items():
            print(f"问题: {question}")
            print(f"出现次数: {len(occurrences)}")
            for occ in occurrences:
                print(f"  - 文件: {occ['file']}, 位置: {occ['index']}, 答案: {occ['answer'][:50]}...")
            print()
    else:
        print("✓ 未发现重复的问题")

if __name__ == "__main__":
    # 生成质量报告
    generate_quality_report()
    
    print("\n" + "=" * 60)
    
    # 查找重复问题
    find_duplicate_questions()