"""Verified resource updates; rollback re-downloads a prior release, without backup ZIPs."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
import requests
import packs
import instance_tools
from resource_catalog import KINDS,install_asset,shader_engines


def installed(game,kind,transfer):
    found={};unknown=0;duplicates=set()
    for path in sorted((Path(game)/KINDS[kind][1]).glob('*.zip')):
        transfer.check()
        if path.is_symlink():unknown+=1;continue
        transfer.notify('Проверяем: '+path.name,0)
        with path.open('rb') as source:digest=hashlib.file_digest(source,'sha512').hexdigest()
        try:release=packs.api('version_file/'+digest,{'algorithm':'sha512'})
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code==404:unknown+=1;continue
            raise
        project=release['project_id'];file=next((f for f in release['files'] if f.get('hashes',{}).get('sha512')==digest),None)
        if not file or not file.get('primary',False):unknown+=1;continue
        if project in found:duplicates.add(project)
        found[project]={'project':project,'release':release,'filename':path.name,'hash':digest}
    for project in duplicates:found.pop(project,None)
    return found,unknown+len(duplicates)


def replace(game,item,kind,current,release,transfer,history=True):
    if item['version'] not in release.get('game_versions',[]) or release.get('project_id')!=current['project']:raise ValueError('Версия ресурса несовместима со сборкой')
    folder=packs.safe_path(game,KINDS[kind][1]);old=packs.safe_path(folder,current['filename'])
    with old.open('rb') as source:
        if hashlib.file_digest(source,'sha512').hexdigest()!=current['hash']:raise ValueError('Файл изменён после проверки: '+old.name)
    files=[f for f in release['files'] if f['filename'].lower().endswith('.zip')]
    if not files:raise ValueError('Нет совместимого ZIP-файла')
    file=next((f for f in files if f.get('primary')),files[0]);target=packs.safe_path(folder,file['filename'])
    if Path(file['filename']).name!=file['filename']:raise ValueError('Недопустимое имя ресурса')
    if target!=old and target.exists():raise ValueError('Целевой файл уже существует: '+target.name)
    with tempfile.TemporaryDirectory(prefix='.asset-update-',dir=Path(game)) as temporary:
        staging=Path(temporary)
        install_asset(staging,{'project_id':current['project']},item['version'],kind,transfer,release_id=release['id'])
        staged=staging/KINDS[kind][1]/file['filename'];transfer.check()
        if history:
            journal=Path(game)/'.asset-history.json'
            data=json.loads(journal.read_text('utf-8')) if journal.exists() else []
            data.append({'kind':kind,'project':current['project'],'previous':current['release']['id'],'current':release['id']})
        if target==old:staged.replace(target)
        else:
            if os.name=='nt':os.rename(staged,target)
            else:os.link(staged,target)
            try:old.unlink()
            except Exception:target.unlink();raise
        if history:instance_tools.write_json(journal,data[-50:])
    return target.name


def update(game,item,kind,transfer):
    found,unknown=installed(game,kind,transfer);count=0
    for project,current in found.items():
        transfer.check()
        versions=packs.api('project/'+project+'/version',{'game_versions':json.dumps([item['version']])})
        engines=shader_engines(game) or set(current['release'].get('loaders',[]))&{'iris','optifine'}
        versions=[v for v in versions if item['version'] in v.get('game_versions',[]) and (kind!='shader' or not engines or engines&set(v.get('loaders',[])))]
        if not versions:continue
        latest=max(versions,key=lambda v:v['date_published'])
        if latest['id']==current['release']['id'] or latest['date_published']<=current['release']['date_published']:continue
        replace(game,item,kind,current,latest,transfer);count+=1
    return f'Обновлено: {count}. Неопознанных файлов или дубликатов пропущено: {unknown}. Старые ZIP-копии не создавались.'


def rollback(game,item,kind,transfer):
    path=Path(game)/'.asset-history.json';journal=json.loads(path.read_text('utf-8')) if path.exists() else []
    index=next((i for i in range(len(journal)-1,-1,-1) if journal[i]['kind']==kind),None)
    if index is None:raise ValueError('Истории обновлений для отката пока нет')
    entry=journal[index];found,_=installed(game,kind,transfer);current=found.get(entry['project'])
    if not current or current['release']['id']!=entry['current']:raise ValueError('Установленный ресурс изменён. Откат этой записи невозможен.')
    previous=packs.api('version/'+entry['previous'])
    name=replace(game,item,kind,current,previous,transfer,False)
    journal.pop(index);instance_tools.write_json(path,journal)
    return 'Предыдущая версия скачана и установлена: '+name

