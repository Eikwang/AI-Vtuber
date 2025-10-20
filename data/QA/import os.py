import os

input_dir = r'D:\AI\AI-Vtuber\data\QA'
output_file = r'D:\AI\AI-Vtuber\data\QA\merged.txt'

with open(output_file, 'w', encoding='utf-8') as outfile:
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            if filename.lower().endswith('.txt') and filename != 'merged.txt':
                file_path = os.path.join(root, filename)
                outfile.write(f'--- {file_path} ---\n')
                with open(file_path, 'r', encoding='utf-8') as infile:
                    outfile.write(infile.read())
                    outfile.write('\n\n')

print('合并完成，输出文件:', output_file)