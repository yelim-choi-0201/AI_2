# Streamlit 배포 복구본 v2

## 업로드할 파일

압축을 푼 뒤 아래 파일을 GitHub 저장소의 첫 화면(루트)에 올립니다.

```text
app.py
requirements.txt
station_daily_usage.csv
station_report.docx       # Word 다운로드용: 선택 파일
.streamlit/config.toml    # 테마용: 선택 파일
```

필수 파일은 app.py, requirements.txt, station_daily_usage.csv 세 개입니다.
기존 analytics.py, charts.py, report_content.py는 수정본에서 사용하지 않습니다.
기존 파일을 삭제하지 않아도 되지만, Streamlit이 실행하는 app.py를 교체해야 합니다.
압축파일 자체만 올리지 말고, 상위 폴더와 실행 경로를 혼동하지 마세요.

## Streamlit Community Cloud 설정

- Repository: 위 파일을 올린 저장소
- Branch: 실제 업로드한 브랜치(예: main)
- Main file path: app.py (루트에 올렸을 때)
- Advanced settings / Python version: 3.13
- Secrets: 필요 없음

기존 앱이 station_usage_app/app.py를 실행한다면 같은 폴더에 수정본을 올려 해당 app.py를 교체하세요.
기존 실행 경로를 바꾸지 않으면 앱을 삭제할 필요가 없습니다.
Python 버전이나 실행 파일 경로를 바꾸는 경우에만 기존 설정을 기록한 뒤 재배포하세요.

## 다음 순서로 확인

1. GitHub에서 수정된 app.py와 requirements.txt의 Commit changes를 완료합니다.
2. Streamlit의 Manage app에서 로그를 열고 Reboot app을 선택합니다.
3. 배포가 완료되면 첫 화면에 63,955건, 5개 탭이 나타나는지 확인합니다.
4. 오류가 있으면 '배포 점검: 파일·설치 버전'을 펼칩니다.
5. 아무 화면도 안 나오면 Manage app의 로그에서 마지막 오류를 확인합니다.

## 수정 내용

- 보조 파일 3개의 기능을 app.py에 통합했습니다.
- CSV의 줄바꿈, UTF-8 BOM, CP949 저장, 행 순서가 달라져도 실제 값이 같으면 통과합니다.
- 숫자, 날짜, 역명 등 실제 데이터가 달라지면 기존 보고서의 결론을 잘못 적용하지 않도록 검증을 유지합니다.
- CSV는 app.py 옆과 data/ 폴더를 순서대로 확인합니다.
- 데이터 로드 전에 제목과 점검 패널을 보여 줍니다.
- 원본 보고서 내용, 집계 기준, 필터, 그래프, 5개 탭을 유지했습니다.

## 로컬 실행

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

이 자료는 수정 소스입니다. 사용자의 공개 앱을 직접 수정하거나 배포 성공을 확인한 것은 아닙니다.
검증 범위와 제약은 VALIDATION.md를 참고하세요.

## 공식 문서

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/reboot-your-app
- https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/upgrade-python
