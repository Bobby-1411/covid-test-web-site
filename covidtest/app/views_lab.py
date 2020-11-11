import os
from django.shortcuts import render
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse

from rest_framework import viewsets
from rest_framework import permissions

from .serializers import SampleSerializer
from .forms_lab import LabCheckInForm, LabQueryForm, LabRackResultsForm, LabProbeEditForm, LabGenerateBarcodeForm
from .models import Sample, RSAKey, Registration, Event
from .statuses import SampleStatus

@login_required
def index(request):
    return render(request, "lab/index.html")

@login_required
def version(request):
    # Checking where the .git directory is
    if os.path.isdir('../.git'):
        git_dir = '../.git'
    elif os.path.isdir('.git'):
        git_dir = '.git'
    else:
        return HttpResponse('No .git directory found')

    with open(git_dir + '/HEAD', 'r') as head:
        ref = head.readline().split(' ')[-1].strip()
        branch_name = ref.split('/')[-1]
    if "/" in ref:
        with open(git_dir + '/' + ref, 'r') as git_hash:
            commit_hash = git_hash.readline().strip()
    else:
        commit_hash = ref

    version_str = """
    <code>
    Branch: <a href='https://github.com/anders-biostat/covid-test-web-site/tree/%s'>%s</a><br>
    Commit: <a href='https://github.com/anders-biostat/covid-test-web-site/commit/%s'>%s</a><br>
    Short: %s <br>
    </code>
    """
    return HttpResponse(version_str % (branch_name, branch_name, commit_hash, commit_hash, commit_hash[:7]))

@login_required
def sample_check_in(request):
    if request.method == 'POST':
        form = LabCheckInForm(request.POST)
        if form.is_valid():
            barcodes = [x.strip().upper() for x in form.data['barcodes'].split()]
            rack = form.cleaned_data['rack'].strip().upper()

            barcodes_not_in_db = []
            status_not_set = []
            rack_not_set = []

            for barcode in barcodes:
                sample = Sample.objects.filter(barcode=barcode).first()
                if not sample:
                    barcodes_not_in_db.append(barcode)
                else:
                    set_rack = sample.modify(rack=rack)
                    set_status = sample.set_status(SampleStatus.WAIT)
                    if not set_rack:
                        rack_not_set.append(barcode)
                    if not set_status:
                        status_not_set.append(barcode)

            if len(barcodes_not_in_db) > 0:
                messages.add_message(request, messages.ERROR, _('Einige Barcodes waren nicht in der Datenbank'))
            if len(status_not_set) > 0:
                messages.add_message(request, messages.ERROR, _('Einige status konnten nicht gesetzt werden'))
            if len(rack_not_set) > 0:
                messages.add_message(request, messages.ERROR, _('Einige racks konnten nicht gesetzt werden'))
            no_success = True
            if len(rack_not_set) == 0 and len(status_not_set) == 0 and len(barcodes_not_in_db) == 0:
                no_success = False
                messages.add_message(request, messages.SUCCESS, _('Proben erfolgreich eingetragen'))

            return render(request, 'lab/sample_check_in.html',
                          {"form": form, "sample": sample, "barcodes_not_in_db": barcodes_not_in_db,
                           "rack_not_set": rack_not_set, "status_not_set": status_not_set, "no_success": no_success})
    else:
        form = LabCheckInForm()
    return render(request, 'lab/sample_check_in.html', {"form": form, "display_sample": False})


@login_required
def sample_edit_rack(request):
    form = LabRackResultsForm()
    if request.method == 'POST':
        form = LabRackResultsForm(request.POST)
        if form.is_valid():
            rack = form.cleaned_data['rack'].upper().strip()
            lamp_positive = form.data['lamp_positive'].split()
            lamp_inconclusive = form.data['lamp_inconclusive'].split()
            lamp_failed = form.data['lamp_failed'].split()
            lamp_positive = [x.replace("\n", "").replace("\r", "").strip() for x in lamp_positive]
            lamp_inconclusive = [x.replace("\n", "").replace("\r", "").strip() for x in lamp_inconclusive]
            lamp_failed = [x.replace("\n", "").replace("\r", "").strip() for x in lamp_inconclusive]

            rack_samples = Sample.objects.filter(rack=rack)
            if len(rack_samples) > 0:
                for sample in rack_samples:
                    status = SampleStatus.LAMPNEG
                    if sample.barcode in lamp_positive:
                        status = SampleStatus.LAMPPOS
                    if sample.barcode in lamp_inconclusive:
                        status = SampleStatus.LAMPINC
                    if sample.barcode in lamp_failed:
                        status = SampleStatus.LAMPFAIL

                    set_status = sample.set_status(status, author=request.user.get_username())
                    barcodes_status_set = []
                    if not set_status:
                        messages.add_message(request, messages.ERROR,
                                             _('Status konnte nicht gesetzt werden: ') + str(sample.barcode))
                    else:
                        barcodes_status_set.append(sample.barcode)
                messages.add_message(request, messages.SUCCESS,
                                     _('Ergebnisse hinzugefügt: ') + ", ".join(barcodes_status_set))
            else:
                messages.add_message(request, messages.ERROR, _('Keine Proben zu Rack gefunden'))

    return render(request, 'lab/sample_rack_results.html', {'form': form})


@login_required
def sample_query(request):
    form = LabQueryForm()
    edit_form = LabProbeEditForm()
    if request.method == 'POST':
        if 'search' in request.POST.keys():
            form = LabQueryForm(request.POST)
            if form.is_valid():
                search = form.cleaned_data['search'].upper().strip()
                sample = Sample.objects.filter(barcode=search).first()
                if sample:
                    edit_form = LabProbeEditForm(initial={'rack': sample.rack})
                return render(request, 'lab/sample_query.html',
                              {'form': form, 'edit_form': edit_form, 'sample': sample, 'search': search})
        if 'edit' in request.POST.keys():
            edit_form = LabProbeEditForm(request.POST)
            if edit_form.is_valid():
                barcode = edit_form.cleaned_data['barcode'].upper().strip()
                status = edit_form.cleaned_data['status'].upper().strip()
                rack = edit_form.cleaned_data['rack'].upper().strip()
                sample = Sample.objects.filter(barcode=barcode).first()
                if sample is None:
                    messages.add_message(request, messages.ERROR, _('Sample nicht gefunde'))
                else:
                    rack_changed = sample.modify(rack=rack)
                    if rack_changed:
                        messages.add_message(request, messages.SUCCESS, _('Sample rack geupdated'))
                    if status != '-':
                        status = SampleStatus[status]
                        event = Event(
                            status=status.value,
                        )
                        event_added = sample.modify(push__events=event)
                        if event_added:
                            messages.add_message(request, messages.SUCCESS, _('Status geupdated'))
                return render(request, 'lab/sample_query.html', {'form': form, 'edit_form': edit_form, 'sample': sample})

    return render(request, 'lab/sample_query.html', {'form': form, 'edit_form': edit_form})


@login_required
def dashboard(request):

    count_wait = Event.objects.filter(status="PRINTED").count()

    dashboard_values = {
        "count_Samples" : Sample.objects.filter().count(),
        "count_wait" : count_wait
    }

    return render(request, "lab/dashboard.html", {'dashboard_values' : dashboard_values})