# Protocolo provisório da busca

## Pergunta de pesquisa

Qual é a produção científica publicada entre 2000 e 2025 sobre
infecções associadas a próteses aloplásticas da articulação
temporomandibular, incluindo prevenção, profilaxia, detecção e controle?

## Estrutura PCC

| Elemento | Definição |
|---|---|
| População | Pacientes submetidos à reconstrução aloplástica da ATM ou publicações sobre essas próteses |
| Conceito | Infecção periprotética, prevenção, profilaxia, detecção, controle, antibióticos e biofilme |
| Contexto | Reconstrução ou substituição aloplástica da articulação temporomandibular, entre 2000 e 2025 |

## Fontes

- PubMed/MEDLINE
- Scopus
- Web of Science

Na etapa inicial, somente o pipeline do PubMed está automatizado.

## Critérios de inclusão provisórios

- publicação entre 2000 e 2025;
- abordar prótese ou substituição aloplástica da ATM;
- abordar infecção, prevenção, profilaxia, detecção ou controle;
- apresentar relação direta com o escopo da revisão;
- possuir informações suficientes para determinar sua relevância.

## Critérios de exclusão provisórios

- reconstrução exclusivamente biológica ou autógena;
- estudo sobre ATM sem relação com prótese aloplástica;
- estudo sobre prótese de outra articulação;
- infecção mencionada apenas incidentalmente;
- registro duplicado;
- publicação fora do período definido.

## Casos incertos

O registro será classificado como incerto quando título e resumo não
forem suficientes para determinar sua inclusão. Esses casos precisarão
de avaliação do texto completo.

## Situação da estratégia

A estratégia de busca atual é provisória e deverá ser ajustada após a
avaliação manual da primeira amostra de 20 registros.

## Dicionário da triagem

### Campo `decision`

Valores permitidos:

| Valor | Significado |
|---|---|
| `include` | O registro atende aos critérios de inclusão. |
| `exclude` | O registro atende a pelo menos um critério de exclusão. |
| `uncertain` | Título e resumo não permitem uma decisão segura. |

### Campo `reason_code`

Cada registro recebe um código principal:

| Código | Decisão associada | Significado |
|---|---|---|
| `DIRECT_SCOPE` | `include` | Atende diretamente ao escopo da revisão. |
| `BIOLOGICAL_RECONSTRUCTION` | `exclude` | Aborda somente reconstrução biológica ou autógena. |
| `NOT_TMJ` | `exclude` | Não trata da articulação temporomandibular. |
| `NOT_PROSTHESIS` | `exclude` | Não trata de prótese ou substituição articular. |
| `NOT_INFECTION` | `exclude` | Não aborda infecção, prevenção, detecção ou controle. |
| `OUTSIDE_PERIOD` | `exclude` | Publicação fora do período definido. |
| `DUPLICATE` | `exclude` | Registro duplicado. |
| `INSUFFICIENT_ABSTRACT` | `uncertain` | Título e resumo não permitem avaliar a elegibilidade. |

Caso existam vários motivos, será registrado o motivo principal em
`reason_code`, e os demais poderão ser descritos em `justification`.

### Campo `justification`

Explicação breve e específica sobre a classificação do registro.

Exemplo:

> O artigo trata de reconstrução autógena, sem utilização de prótese
> aloplástica.

### Campo `reviewer`

Identificador de quem realizou a avaliação, por exemplo:

- `reviewer_01`
- `reviewer_02`

Cada avaliador deve utilizar sempre o mesmo identificador.