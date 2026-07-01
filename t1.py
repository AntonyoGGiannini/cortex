import json
import sys

import server

sys.stdout.reconfigure(encoding="utf-8")

# 1. Listar gravações
gravacoes_json = server.list_recordings(limit=5)
gravacoes = json.loads(gravacoes_json)


# exit()
# print("Gravações:")
# for g in gravacoes:
#     print(g["id"], "-", g["name"])

# 2. Pegar o ID da primeira gravação
file_id = gravacoes[0]["id"]

#print(gravacoes[0])
# 3. Buscar detalhes
detalhes = server.get_recording_detail(file_id)
# print("\nDetalhes:")
# print(detalhes)

#print('--------------------------')
# 4. Buscar transcrição
# transcricao = server.get_transcript(file_id)
# print("\nTranscrição:")
# print(transcricao)
# print('--------------------------')
# 5. Buscar resumo
# resumo = server.get_summary(file_id)
# print("\nResumo:")
# print(resumo)
